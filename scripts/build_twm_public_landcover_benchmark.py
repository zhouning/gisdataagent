#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import warnings
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_twm_dongguan_geosos_validation import (  # noqa: E402
    DEFAULT_INPUT as DEFAULT_DONGGUAN_ZIP,
    extract_zip,
    landuse_label,
    load_landuse_rasters,
    parse_landuse_info,
)
from scripts.run_twm_flus_v24_simulation_optimization import normalize_01  # noqa: E402


DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_public_landcover_benchmark_2026-06-22.json"
DEFAULT_MARKDOWN = REPO_ROOT / "docs/twm-public-landcover-benchmark-2026-06-22.md"
DEFAULT_ASSET_DIR = REPO_ROOT / "docs/assets"


@dataclass(frozen=True)
class LandcoverFrame:
    year: int
    array: np.ndarray
    path: str
    nodata: int | float | None = None


@dataclass(frozen=True)
class BenchmarkRegion:
    region_id: str
    frames: tuple[LandcoverFrame, ...]
    classes: tuple[int, ...]
    class_labels: dict[int, str]
    cell_area_ha: float
    drivers: dict[str, np.ndarray]
    source: dict[str, Any]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a multi-period public land-cover benchmark for TWM transition dynamics."
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--manifest",
        type=Path,
        help="Manifest JSON for local public land-cover raster stacks such as GLC_FCS30D or Dynamic World exports.",
    )
    source_group.add_argument(
        "--dongguan-zip",
        type=Path,
        default=None,
        help="Use the existing GeoSOS DongGuan 80m zip as a real-data adapter for the generic benchmark.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()

    dongguan_zip = args.dongguan_zip
    if args.manifest is None and dongguan_zip is None:
        dongguan_zip = DEFAULT_DONGGUAN_ZIP

    report = run_public_landcover_benchmark(
        manifest_path=args.manifest,
        dongguan_zip=dongguan_zip,
        asset_dir=args.asset_dir,
        render=not args.no_render,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown_report(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))


def run_public_landcover_benchmark(
    *,
    manifest_path: Path | None = None,
    dongguan_zip: Path | None = None,
    asset_dir: Path | None = None,
    render: bool = True,
) -> dict[str, Any]:
    if manifest_path is None and dongguan_zip is None:
        raise ValueError("Either manifest_path or dongguan_zip must be provided.")
    if manifest_path is not None and dongguan_zip is not None:
        raise ValueError("Use either manifest_path or dongguan_zip, not both.")

    if manifest_path is not None:
        regions, source = load_manifest_regions(manifest_path)
    else:
        regions, source = load_dongguan_region(Path(dongguan_zip or DEFAULT_DONGGUAN_ZIP))

    cross_region_priors = build_cross_region_transition_priors(regions)
    experiments: list[dict[str, Any]] = []
    for region in regions:
        experiments.extend(run_region_cases(region, cross_region_priors=cross_region_priors))

    summary = aggregate_experiments(experiments)
    assets: dict[str, str] = {}
    if render and asset_dir is not None and experiments:
        asset_dir.mkdir(parents=True, exist_ok=True)
        assets = render_assets(asset_dir=asset_dir, regions=regions, experiments=experiments, summary=summary)

    status = "pass" if experiments else "blocked"
    return {
        "schema": "territory_world_model.public_landcover_benchmark.v1",
        "status": status,
        "claim_boundary": "public_or_public_like_landcover_benchmark_engineering_validation_not_production_or_general_superiority_claim",
        "source": source,
        "data_profile": {
            "region_count": len(regions),
            "case_count": len(experiments),
            "regions": [region_profile(region) for region in regions],
        },
        "benchmark_design": {
            "temporal_protocol": "rolling_three_frame_train_validate: train t0->t1 and evaluate t1->t2",
            "spatial_protocol": "each region is evaluated independently; multi-region manifests enable region-level aggregation",
            "candidate_ids": [
                "persistence",
                "markov_transition_projection",
                "twm_independent_transition_forecast_demand",
                "twm_hierarchical_transition_forecast_demand",
                "twm_calibrated_hierarchical_transition_forecast_demand",
                "twm_cross_region_smoothed_transition_forecast_demand",
                "twm_ablation_no_drivers_forecast_demand",
                "twm_ablation_no_neighborhood_forecast_demand",
                "twm_ablation_no_transition_prior_forecast_demand",
                "twm_ablation_no_demand_projection",
                "twm_independent_transition_oracle_demand",
            ],
            "demand_modes": {
                "forecast_demand": "Class totals are projected only from t0 and t1; this is the formal prediction setting.",
                "oracle_demand": "Class totals are copied from t2; this is an upper-bound diagnostic and must not be used as a real forecast claim.",
                "no_demand_projection": "No class-total projection or quota repair is applied; this is a component ablation, not a planning forecast.",
            },
        },
        "experiments": experiments,
        "summary": summary,
        "renderer": {"rendered": bool(assets), "assets": assets},
        "interpretation": {
            "what_this_adds": [
                "A generic benchmark entry point for local public land-cover raster stacks such as GLC_FCS30D, Dynamic World exports or MODIS annual land-cover products.",
                "The same evaluator can also ingest the existing DongGuan sample as a real-data adapter, so development does not depend on synthetic fixtures.",
                "The report separates forecast-demand results from oracle-demand upper bounds, preventing target-year class totals from being hidden inside a claimed forecast.",
            ],
            "what_is_still_missing": [
                "A true TWM paper claim still needs a multi-region manifest from public data rather than one tutorial region.",
                "The current independent dynamics candidate uses transparent logit/neighborhood transition modelling, not a fully trained neural world model.",
                "A rigorous FLUS comparison still needs consistent multi-region baselines and scenario-demand assumptions, not only package-provided sample outputs.",
            ],
            "next_tasks": [
                "Build a GLC_FCS30D manifest for 20-50 regions and years such as 2000/2005/2010/2015/2020/2022.",
                "Add region-holdout aggregation, where model parameters are trained on source regions and evaluated on unseen target regions.",
                "Add ablations for no-neighborhood, no-drivers, no-transition-prior and no-demand-projection variants.",
                "Add a non-leaky scenario/demand model using historical trends and external covariates before making policy forecasting claims.",
            ],
        },
    }


def load_manifest_regions(manifest_path: Path) -> tuple[list[BenchmarkRegion], dict[str, Any]]:
    manifest_path = manifest_path.expanduser()
    if not manifest_path.exists():
        raise FileNotFoundError(str(manifest_path))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_dir = manifest_path.parent
    class_payload = manifest.get("classes") or []
    if not class_payload:
        raise ValueError("Manifest must include a non-empty classes list.")
    classes = tuple(sorted(int(item["value"]) for item in class_payload))
    labels = {int(item["value"]): str(item.get("label") or item["value"]) for item in class_payload}
    regions: list[BenchmarkRegion] = []
    for region_payload in manifest.get("regions") or []:
        region_id = str(region_payload.get("region_id") or region_payload.get("id") or f"region_{len(regions) + 1}")
        frame_payload = region_payload.get("raster_stack") or region_payload.get("frames") or []
        frames = tuple(load_manifest_frames(frame_payload, base_dir=base_dir, default_nodata=region_payload.get("nodata")))
        if len(frames) < 3:
            raise ValueError(f"Region {region_id} must include at least three land-cover frames.")
        shape = frames[0].array.shape
        if any(frame.array.shape != shape for frame in frames):
            raise ValueError(f"Region {region_id} contains rasters with inconsistent shapes.")
        drivers = load_manifest_drivers(region_payload.get("driver_layers") or [], base_dir=base_dir, shape=shape)
        regions.append(
            BenchmarkRegion(
                region_id=region_id,
                frames=tuple(sorted(frames, key=lambda frame: frame.year)),
                classes=classes,
                class_labels=labels,
                cell_area_ha=float(region_payload.get("cell_area_ha") or manifest.get("cell_area_ha") or 1.0),
                drivers=drivers,
                source={
                    "source_type": "manifest",
                    "manifest_path": str(manifest_path),
                    "dataset_id": manifest.get("dataset_id") or manifest.get("name") or "public_landcover_manifest",
                },
            )
        )
    if not regions:
        raise ValueError("Manifest must include at least one region.")
    return regions, {
        "source_type": "manifest",
        "manifest_path": str(manifest_path),
        "dataset_id": manifest.get("dataset_id") or manifest.get("name") or "public_landcover_manifest",
        "declared_source": manifest.get("source") or {},
    }


def load_manifest_frames(
    frame_payload: list[dict[str, Any]],
    *,
    base_dir: Path,
    default_nodata: int | float | None,
) -> list[LandcoverFrame]:
    import rasterio

    frames: list[LandcoverFrame] = []
    for payload in frame_payload:
        path = resolve_path(base_dir, payload.get("path") or payload.get("raster"))
        year = int(payload["year"])
        with rasterio.open(path) as src:
            data = src.read(1, masked=True)
            nodata = payload.get("nodata", default_nodata if default_nodata is not None else src.nodata)
            arr = np.asarray(data.filled(nodata if nodata is not None else 0), dtype=np.int16)
        frames.append(LandcoverFrame(year=year, array=arr, path=str(path), nodata=nodata))
    return frames


def load_manifest_drivers(
    driver_payload: list[dict[str, Any]],
    *,
    base_dir: Path,
    shape: tuple[int, int],
) -> dict[str, np.ndarray]:
    import rasterio

    drivers: dict[str, np.ndarray] = {}
    for payload in driver_payload:
        name = str(payload.get("name") or payload.get("id") or payload.get("path"))
        path = resolve_path(base_dir, payload.get("path") or payload.get("raster"))
        with rasterio.open(path) as src:
            data = src.read(1, masked=True).astype(np.float32)
            arr = np.asarray(data.filled(np.nan), dtype=np.float32)
        if arr.shape != shape:
            raise ValueError(f"Driver {name} has shape {arr.shape}, expected {shape}.")
        drivers[name] = normalize_01(arr)
    return drivers


def resolve_path(base_dir: Path, value: Any) -> Path:
    if not value:
        raise ValueError("Missing path in manifest.")
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def load_dongguan_region(zip_path: Path) -> tuple[list[BenchmarkRegion], dict[str, Any]]:
    zip_path = zip_path.expanduser()
    if not zip_path.exists():
        raise FileNotFoundError(str(zip_path))
    with tempfile.TemporaryDirectory(prefix="twm_public_benchmark_dongguan_") as tmp:
        root = extract_zip(zip_path, Path(tmp))
        landuse_info = parse_landuse_info(root / "Config Files" / "DefaultLanduseInfo.xml")
        rasters = load_landuse_rasters(root)
        classes = tuple(sorted(int(value) for value in (landuse_info.get("types") or {})))
        labels = {cls: landuse_label(landuse_info, cls) for cls in classes}
        frames = tuple(
            LandcoverFrame(year=year, array=payload["data"].astype(np.int16), path=str(payload["path"]), nodata=payload.get("nodata"))
            for year, payload in sorted(rasters.items())
        )
        first = next(iter(rasters.values()))
        resolution = first.get("resolution")
        transform = first.get("transform")
        if resolution is not None:
            cell_area_ha = abs(float(resolution[0]) * float(resolution[1])) / 10000.0
        elif transform is not None and len(transform) >= 5:
            cell_area_ha = abs(float(transform[0]) * float(transform[4])) / 10000.0
        else:
            cell_area_ha = 0.64
        drivers = load_dongguan_drivers(root, frames[0].array.shape)
    region = BenchmarkRegion(
        region_id="dongguan_80m",
        frames=frames,
        classes=classes,
        class_labels=labels,
        cell_area_ha=cell_area_ha,
        drivers=drivers,
        source={
            "source_type": "dongguan_zip_adapter",
            "zip_path": str(zip_path),
            "dataset_id": "GeoSOS DongGuan 80m tutorial data",
        },
    )
    return [region], {
        "source_type": "dongguan_zip_adapter",
        "zip_path": str(zip_path),
        "dataset_id": "GeoSOS DongGuan 80m tutorial data",
    }


def load_dongguan_drivers(root: Path, shape: tuple[int, int]) -> dict[str, np.ndarray]:
    import rasterio

    candidates = {
        "dtcity": root / "Variables Data" / "dtcity",
        "dtfreeway": root / "Variables Data" / "dtfreeway",
        "dtrailway": root / "Variables Data" / "dtrailway",
        "dtroad": root / "Variables Data" / "dtroad",
    }
    drivers: dict[str, np.ndarray] = {}
    for name, path in candidates.items():
        if not path.exists():
            continue
        with rasterio.open(path) as src:
            data = src.read(1, masked=True).astype(np.float32)
            arr = np.asarray(data.filled(np.nan), dtype=np.float32)
        if arr.shape == shape:
            drivers[name] = normalize_01(arr)
            drivers[f"near_{name[2:]}" if name.startswith("dt") else f"near_{name}"] = 1.0 - drivers[name]
    return drivers


def build_cross_region_transition_priors(regions: list[BenchmarkRegion]) -> dict[str, Any]:
    periods: dict[str, dict[str, Any]] = {}
    for region in regions:
        frames = list(region.frames)
        for idx in range(len(frames) - 1):
            start = frames[idx]
            end = frames[idx + 1]
            valid = transition_pair_valid_mask(start, end, region.classes)
            key = transition_period_key(start.year, end.year)
            source_counts = Counter(start.array[valid].astype(int).tolist())
            pair_counts = Counter(zip(start.array[valid].astype(int), end.array[valid].astype(int)))
            period = periods.setdefault(
                key,
                {
                    "train_start_year": int(start.year),
                    "train_end_year": int(end.year),
                    "regions": {},
                    "aggregate_source_counts": Counter(),
                    "aggregate_pair_counts": Counter(),
                    "valid_cell_count": 0,
                },
            )
            period["regions"][region.region_id] = {
                "source_counts": source_counts,
                "pair_counts": pair_counts,
                "valid_cell_count": int(valid.sum()),
            }
            period["aggregate_source_counts"].update(source_counts)
            period["aggregate_pair_counts"].update(pair_counts)
            period["valid_cell_count"] += int(valid.sum())
    return {
        "schema": "territory_world_model.cross_region_transition_priors.v1",
        "region_count": len(regions),
        "period_count": len(periods),
        "periods": periods,
    }


def transition_period_key(start_year: int, end_year: int) -> str:
    return f"{int(start_year)}->{int(end_year)}"


def transition_pair_valid_mask(
    start: LandcoverFrame,
    end: LandcoverFrame,
    classes: tuple[int, ...],
) -> np.ndarray:
    class_values = np.asarray(classes)
    valid = np.isin(start.array, class_values) & np.isin(end.array, class_values)
    for frame in (start, end):
        if frame.nodata is not None:
            valid &= frame.array != frame.nodata
    return valid


def run_region_cases(region: BenchmarkRegion, *, cross_region_priors: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    frames = list(region.frames)
    for idx in range(len(frames) - 2):
        train_start = frames[idx]
        train_end = frames[idx + 1]
        holdout = frames[idx + 2]
        valid = valid_mask(train_start, train_end, holdout, region.classes)
        if int(valid.sum()) == 0:
            continue
        model_inputs = {
            "train_start": train_start.array,
            "train_end": train_end.array,
            "initial": train_end.array,
            "actual": holdout.array,
            "valid": valid,
            "classes": list(region.classes),
            "drivers": region.drivers,
            "train_years": max(1, train_end.year - train_start.year),
            "horizon_years": max(1, holdout.year - train_end.year),
            "region_id": region.region_id,
            "train_start_year": int(train_start.year),
            "train_end_year": int(train_end.year),
            "holdout_year": int(holdout.year),
        }
        forecast_counts = project_class_counts(
            train_start.array,
            train_end.array,
            valid,
            list(region.classes),
            train_years=model_inputs["train_years"],
            horizon_years=model_inputs["horizon_years"],
        )
        oracle_counts = class_counts(holdout.array, valid, list(region.classes))
        predictions, metadata = build_candidates(
            model_inputs,
            forecast_counts,
            oracle_counts,
            cross_region_priors=cross_region_priors,
        )
        metrics = {
            name: pixel_metrics(
                prediction=pred,
                actual=holdout.array,
                initial=train_end.array,
                valid=valid,
                classes=list(region.classes),
                cell_area_ha=region.cell_area_ha,
                target_counts=metadata[name]["target_counts"],
            )
            for name, pred in predictions.items()
        }
        best_forecast = max(
            [name for name, payload in metadata.items() if payload["demand_mode"] == "forecast_demand"],
            key=lambda name: metrics[name]["change_fom"],
        )
        best_oracle = max(
            [name for name, payload in metadata.items() if payload["demand_mode"] == "oracle_demand"],
            key=lambda name: metrics[name]["change_fom"],
        )
        cases.append(
            {
                "case_id": f"{region.region_id}_{train_start.year}_{train_end.year}_{holdout.year}",
                "region_id": region.region_id,
                "train_period": f"{train_start.year}->{train_end.year}",
                "holdout_period": f"{train_end.year}->{holdout.year}",
                "valid_cell_count": int(valid.sum()),
                "cell_area_ha": region.cell_area_ha,
                "class_labels": {str(key): value for key, value in region.class_labels.items()},
                "demand": {
                    "forecast_counts": {str(key): value for key, value in forecast_counts.items()},
                    "oracle_counts": {str(key): value for key, value in oracle_counts.items()},
                    "forecast_total_abs_error_against_oracle": int(
                        sum(abs(int(forecast_counts.get(cls, 0)) - int(oracle_counts.get(cls, 0))) for cls in region.classes)
                    ),
                },
                "candidate_metadata": metadata,
                "metrics": metrics,
                "ablation_summary": build_ablation_summary(metrics),
                "best_forecast_by_change_fom": best_forecast,
                "best_oracle_by_change_fom": best_oracle,
                "claim_boundary": "single rolling case; only aggregate multi-region results should be used for research claims",
            }
        )
    return cases


def valid_mask(
    train_start: LandcoverFrame,
    train_end: LandcoverFrame,
    holdout: LandcoverFrame,
    classes: tuple[int, ...],
) -> np.ndarray:
    class_values = np.asarray(classes)
    valid = np.isin(train_start.array, class_values) & np.isin(train_end.array, class_values) & np.isin(holdout.array, class_values)
    for frame in (train_start, train_end, holdout):
        if frame.nodata is not None:
            valid &= frame.array != frame.nodata
    return valid


def class_counts(arr: np.ndarray, valid: np.ndarray, classes: list[int]) -> dict[int, int]:
    values = arr[valid].astype(int)
    counts = Counter(values.tolist())
    return {int(cls): int(counts.get(int(cls), 0)) for cls in classes}


def project_class_counts(
    start: np.ndarray,
    end: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    *,
    train_years: int,
    horizon_years: int,
) -> dict[int, int]:
    start_counts = class_counts(start, valid, classes)
    end_counts = class_counts(end, valid, classes)
    ratio = float(horizon_years) / max(1.0, float(train_years))
    raw = {
        cls: max(0.0, float(end_counts[cls]) + (float(end_counts[cls]) - float(start_counts[cls])) * ratio)
        for cls in classes
    }
    total = int(valid.sum())
    raw_total = float(sum(raw.values()))
    if raw_total <= 0:
        raw = {cls: float(end_counts[cls]) for cls in classes}
        raw_total = float(sum(raw.values()))
    if raw_total > 0:
        raw = {cls: raw[cls] * total / raw_total for cls in classes}
    floors = {cls: int(math.floor(raw[cls])) for cls in classes}
    remaining = total - sum(floors.values())
    fractional_order = sorted(classes, key=lambda cls: (raw[cls] - floors[cls], end_counts[cls]), reverse=True)
    if remaining >= 0:
        for cls in fractional_order[:remaining]:
            floors[cls] += 1
    else:
        for cls in sorted(classes, key=lambda cls: (floors[cls], -(raw[cls] - floors[cls])), reverse=True):
            if remaining == 0:
                break
            take = min(floors[cls], -remaining)
            floors[cls] -= take
            remaining += take
    return {int(cls): int(floors[cls]) for cls in classes}


def build_candidates(
    model_inputs: dict[str, Any],
    forecast_counts: dict[int, int],
    oracle_counts: dict[int, int],
    *,
    cross_region_priors: dict[str, Any] | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    probability, training_diagnostics = train_transition_probability_cube(model_inputs, include_drivers=True, include_neighborhood=True)
    score = transition_score_cube(model_inputs, probability, include_neighborhood=True, include_prior=True)
    cross_region_probability, cross_region_diagnostics = apply_cross_region_smoothed_transition_probability_cube(
        model_inputs,
        base_probability=probability,
        cross_region_priors=cross_region_priors,
    )
    cross_region_score = transition_score_cube(
        model_inputs,
        cross_region_probability,
        include_neighborhood=True,
        include_prior=True,
    )
    hierarchical_outputs = train_hierarchical_transition_probability_cubes(
        model_inputs,
        include_drivers=True,
        include_neighborhood=True,
        pooled_fallback_weights={
            "fixed": 1.0,
            "calibrated": "auto",
        },
    )
    hierarchical_probability, hierarchical_diagnostics = hierarchical_outputs["fixed"]
    hierarchical_score = transition_score_cube(model_inputs, hierarchical_probability, include_neighborhood=True, include_prior=True)
    calibrated_hierarchical_probability, calibrated_hierarchical_diagnostics = hierarchical_outputs["calibrated"]
    calibrated_hierarchical_score = transition_score_cube(
        model_inputs,
        calibrated_hierarchical_probability,
        include_neighborhood=True,
        include_prior=True,
    )
    no_driver_probability, no_driver_diagnostics = train_transition_probability_cube(model_inputs, include_drivers=False, include_neighborhood=True)
    no_driver_score = transition_score_cube(model_inputs, no_driver_probability, include_neighborhood=True, include_prior=True)
    no_neighborhood_probability, no_neighborhood_diagnostics = train_transition_probability_cube(model_inputs, include_drivers=True, include_neighborhood=False)
    no_neighborhood_score = transition_score_cube(model_inputs, no_neighborhood_probability, include_neighborhood=False, include_prior=True)
    no_prior_score = transition_score_cube(model_inputs, probability, include_neighborhood=True, include_prior=False)
    predictions = {
        "persistence": model_inputs["initial"].copy(),
        "markov_transition_projection": allocate_markov_projection(model_inputs, forecast_counts),
        "twm_independent_transition_forecast_demand": allocate_score_projection(model_inputs, forecast_counts, score),
        "twm_hierarchical_transition_forecast_demand": allocate_score_projection(model_inputs, forecast_counts, hierarchical_score),
        "twm_calibrated_hierarchical_transition_forecast_demand": allocate_score_projection(
            model_inputs,
            forecast_counts,
            calibrated_hierarchical_score,
        ),
        "twm_cross_region_smoothed_transition_forecast_demand": allocate_score_projection(
            model_inputs,
            forecast_counts,
            cross_region_score,
        ),
        "twm_ablation_no_drivers_forecast_demand": allocate_score_projection(model_inputs, forecast_counts, no_driver_score),
        "twm_ablation_no_neighborhood_forecast_demand": allocate_score_projection(model_inputs, forecast_counts, no_neighborhood_score),
        "twm_ablation_no_transition_prior_forecast_demand": allocate_score_projection(model_inputs, forecast_counts, no_prior_score),
        "twm_ablation_no_demand_projection": allocate_free_score_assignment(model_inputs, score),
        "twm_independent_transition_oracle_demand": allocate_score_projection(model_inputs, oracle_counts, score),
    }
    for pred in predictions.values():
        pred[~model_inputs["valid"]] = 0
    metadata = {
        "persistence": {
            "backend": "no_change_baseline",
            "demand_mode": "forecast_demand",
            "uses_holdout_labels_for_training": False,
            "target_counts": forecast_counts,
        },
        "markov_transition_projection": {
            "backend": "observed_pair_markov_transition_projection",
            "demand_mode": "forecast_demand",
            "uses_holdout_labels_for_training": False,
            "target_counts": forecast_counts,
        },
        "twm_independent_transition_forecast_demand": {
            "backend": "action_conditioned_logit_neighborhood_transition",
            "demand_mode": "forecast_demand",
            "uses_holdout_labels_for_training": False,
            "component_flags": {
                "driver_features": True,
                "neighborhood_features": True,
                "transition_prior": True,
                "demand_projection": True,
            },
            "training_diagnostics": training_diagnostics,
            "target_counts": forecast_counts,
        },
        "twm_hierarchical_transition_forecast_demand": {
            "backend": "hierarchical_pooled_action_conditioned_logit_neighborhood_transition",
            "demand_mode": "forecast_demand",
            "uses_holdout_labels_for_training": False,
            "component_flags": {
                "driver_features": True,
                "neighborhood_features": True,
                "transition_prior": True,
                "demand_projection": True,
                "hierarchical_pooling": True,
            },
            "training_diagnostics": hierarchical_diagnostics,
            "target_counts": forecast_counts,
        },
        "twm_calibrated_hierarchical_transition_forecast_demand": {
            "backend": "calibrated_hierarchical_pooled_action_conditioned_logit_neighborhood_transition",
            "demand_mode": "forecast_demand",
            "uses_holdout_labels_for_training": False,
            "component_flags": {
                "driver_features": True,
                "neighborhood_features": True,
                "transition_prior": True,
                "demand_projection": True,
                "hierarchical_pooling": True,
                "calibrated_pooling": True,
            },
            "training_diagnostics": calibrated_hierarchical_diagnostics,
            "target_counts": forecast_counts,
        },
        "twm_cross_region_smoothed_transition_forecast_demand": {
            "backend": "leave_region_out_empirical_bayes_transition_smoothing",
            "demand_mode": "forecast_demand",
            "uses_holdout_labels_for_training": False,
            "component_flags": {
                "driver_features": True,
                "neighborhood_features": True,
                "transition_prior": True,
                "demand_projection": True,
                "cross_region_transition_smoothing": True,
                "leave_region_out": True,
            },
            "training_diagnostics": cross_region_diagnostics,
            "target_counts": forecast_counts,
        },
        "twm_ablation_no_drivers_forecast_demand": {
            "backend": "action_conditioned_logit_neighborhood_transition",
            "ablation_of": "twm_independent_transition_forecast_demand",
            "demand_mode": "forecast_demand",
            "uses_holdout_labels_for_training": False,
            "component_flags": {
                "driver_features": False,
                "neighborhood_features": True,
                "transition_prior": True,
                "demand_projection": True,
            },
            "training_diagnostics": no_driver_diagnostics,
            "target_counts": forecast_counts,
        },
        "twm_ablation_no_neighborhood_forecast_demand": {
            "backend": "action_conditioned_logit_transition",
            "ablation_of": "twm_independent_transition_forecast_demand",
            "demand_mode": "forecast_demand",
            "uses_holdout_labels_for_training": False,
            "component_flags": {
                "driver_features": True,
                "neighborhood_features": False,
                "transition_prior": True,
                "demand_projection": True,
            },
            "training_diagnostics": no_neighborhood_diagnostics,
            "target_counts": forecast_counts,
        },
        "twm_ablation_no_transition_prior_forecast_demand": {
            "backend": "action_conditioned_logit_neighborhood_transition",
            "ablation_of": "twm_independent_transition_forecast_demand",
            "demand_mode": "forecast_demand",
            "uses_holdout_labels_for_training": False,
            "component_flags": {
                "driver_features": True,
                "neighborhood_features": True,
                "transition_prior": False,
                "demand_projection": True,
            },
            "training_diagnostics": training_diagnostics,
            "target_counts": forecast_counts,
        },
        "twm_ablation_no_demand_projection": {
            "backend": "action_conditioned_logit_neighborhood_transition",
            "ablation_of": "twm_independent_transition_forecast_demand",
            "demand_mode": "no_demand_projection",
            "uses_holdout_labels_for_training": False,
            "component_flags": {
                "driver_features": True,
                "neighborhood_features": True,
                "transition_prior": True,
                "demand_projection": False,
            },
            "training_diagnostics": training_diagnostics,
            "target_counts": forecast_counts,
        },
        "twm_independent_transition_oracle_demand": {
            "backend": "action_conditioned_logit_neighborhood_transition",
            "demand_mode": "oracle_demand",
            "uses_holdout_labels_for_training": False,
            "uses_holdout_class_totals": True,
            "component_flags": {
                "driver_features": True,
                "neighborhood_features": True,
                "transition_prior": True,
                "demand_projection": True,
            },
            "training_diagnostics": training_diagnostics,
            "target_counts": oracle_counts,
        },
    }
    return predictions, metadata


def train_transition_probability_cube(
    model_inputs: dict[str, Any],
    *,
    include_drivers: bool,
    include_neighborhood: bool,
) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception:
        return transition_prior_probability_cube(model_inputs), {
            "schema": "territory_world_model.public_landcover_training_diagnostics.v1",
            "backend": "transition_prior_probability_cube",
            "status": "fallback",
            "reason": "sklearn_unavailable",
        }

    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = list(model_inputs["classes"])
    features_train = feature_stack(
        train_start,
        valid,
        classes,
        model_inputs["drivers"],
        include_drivers=include_drivers,
        include_neighborhood=include_neighborhood,
    )
    features_apply = feature_stack(
        initial,
        valid,
        classes,
        model_inputs["drivers"],
        include_drivers=include_drivers,
        include_neighborhood=include_neighborhood,
    )
    rows, cols = np.indices(train_start.shape)
    sample_stride = 2 if int(valid.sum()) > 25000 else 1
    train_mask = valid & (((rows + cols) % sample_stride) == 0)
    out = np.zeros((len(classes), train_start.shape[0], train_start.shape[1]), dtype=np.float32)
    global_prior = global_target_prior(train_end, valid, classes)
    source_reports: list[dict[str, Any]] = []
    for source in classes:
        source_train = train_mask & (train_start == source)
        source_apply = valid & (initial == source)
        if int(source_train.sum()) < max(12, len(classes) * 4) or len(np.unique(train_end[source_train])) < 2:
            out[:, source_apply] = global_prior[:, None]
            source_reports.append(
                {
                    "source_class": int(source),
                    "status": "fallback_global_prior",
                    "train_sample_count": int(source_train.sum()),
                    "apply_cell_count": int(source_apply.sum()),
                    "observed_target_class_count": int(len(np.unique(train_end[source_train]))),
                }
            )
            continue
        model, report = fit_transition_classifier(
            features_train[source_train],
            train_end[source_train].astype(int),
            source_class=int(source),
            train_sample_count=int(source_train.sum()),
            apply_cell_count=int(source_apply.sum()),
            convergence_warning=ConvergenceWarning,
        )
        source_reports.append(report)
        if model is None:
            values = transition_prior_for_source(model_inputs, int(source), global_prior)
            out[:, source_apply] = values[:, None]
            continue
        probs = model.predict_proba(features_apply[source_apply])
        estimator = model.named_steps["logisticregression"]
        class_to_col = {int(cls): idx for idx, cls in enumerate(estimator.classes_)}
        for target_idx, target in enumerate(classes):
            col = class_to_col.get(int(target))
            if col is not None:
                out[target_idx, source_apply] = probs[:, col]
    out[:, ~valid] = 0.0
    return out, build_training_diagnostics(
        include_drivers=include_drivers,
        include_neighborhood=include_neighborhood,
        sample_stride=sample_stride,
        source_reports=source_reports,
    )


def apply_cross_region_smoothed_transition_probability_cube(
    model_inputs: dict[str, Any],
    *,
    base_probability: np.ndarray,
    cross_region_priors: dict[str, Any] | None,
) -> tuple[np.ndarray, dict[str, Any]]:
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = list(model_inputs["classes"])
    region_id = str(model_inputs.get("region_id") or "")
    period_key = transition_period_key(int(model_inputs["train_start_year"]), int(model_inputs["train_end_year"]))
    out = base_probability.copy()
    prior_by_source, prior_report = leave_region_out_transition_priors(
        model_inputs=model_inputs,
        cross_region_priors=cross_region_priors,
        period_key=period_key,
        region_id=region_id,
    )
    source_reports: list[dict[str, Any]] = []
    if not prior_by_source:
        source_reports = [
            {
                "source_class": int(source),
                "status": "base_probability_no_cross_region_support",
                "train_sample_count": int((valid & (train_start == source)).sum()),
                "apply_cell_count": int((valid & (initial == source)).sum()),
            }
            for source in classes
        ]
        return out, build_cross_region_smoothing_diagnostics(
            source_reports=source_reports,
            period_key=period_key,
            region_id=region_id,
            prior_report=prior_report,
        )

    weights, weight_report = choose_cross_region_smoothing_weights(
        model_inputs=model_inputs,
        base_probability=base_probability,
        prior_by_source=prior_by_source,
        classes=classes,
    )
    class_to_idx = {int(cls): idx for idx, cls in enumerate(classes)}
    for source in classes:
        source_apply = valid & (initial == source)
        source_train = valid & (train_start == source)
        prior_values = prior_by_source.get(int(source))
        weight = float(weights.get(int(source), 0.0))
        if prior_values is None:
            source_reports.append(
                {
                    "source_class": int(source),
                    "status": "base_probability_no_peer_source_support",
                    "train_sample_count": int(source_train.sum()),
                    "apply_cell_count": int(source_apply.sum()),
                    "smoothing_weight": 0.0,
                }
            )
            continue
        if int(source_apply.sum()) > 0 and weight > 0.0:
            mixed_block = out[:, source_apply].copy()
            for target_idx, _target in enumerate(classes):
                mixed_block[target_idx] = (
                    (1.0 - weight) * mixed_block[target_idx]
                    + weight * float(prior_values[target_idx])
                )
            totals = mixed_block.sum(axis=0, keepdims=True)
            np.divide(mixed_block, totals, out=mixed_block, where=totals > 0)
            out[:, source_apply] = mixed_block
        source_reports.append(
            {
                "source_class": int(source),
                "status": "cross_region_smoothed" if weight > 0.0 else "base_probability_calibrated_zero_weight",
                "train_sample_count": int(source_train.sum()),
                "apply_cell_count": int(source_apply.sum()),
                "observed_target_class_count": int(len(np.unique(train_end[source_train]))),
                "peer_source_count": int(prior_report.get("peer_source_counts", {}).get(str(source), 0)),
                "smoothing_weight": round(weight, 6),
                "peer_target_classes": [
                    int(classes[idx])
                    for idx, value in enumerate(prior_values)
                    if float(value) > 0.0
                ],
                "base_class_probability": round(
                    float(np.mean(base_probability[class_to_idx[int(source)], source_apply]))
                    if int(source_apply.sum()) > 0 and int(source) in class_to_idx
                    else 0.0,
                    6,
                ),
            }
        )
    out[:, ~valid] = 0.0
    return out, build_cross_region_smoothing_diagnostics(
        source_reports=source_reports,
        period_key=period_key,
        region_id=region_id,
        prior_report={**prior_report, "weight_report": weight_report},
    )


def leave_region_out_transition_priors(
    *,
    model_inputs: dict[str, Any],
    cross_region_priors: dict[str, Any] | None,
    period_key: str,
    region_id: str,
) -> tuple[dict[int, np.ndarray], dict[str, Any]]:
    classes = list(model_inputs["classes"])
    if not cross_region_priors:
        return {}, {
            "status": "unavailable",
            "reason": "cross_region_priors_not_provided",
            "period_key": period_key,
            "region_id": region_id,
        }
    period = (cross_region_priors.get("periods") or {}).get(period_key)
    if not period:
        return {}, {
            "status": "unavailable",
            "reason": "period_not_found",
            "period_key": period_key,
            "region_id": region_id,
        }
    regions = period.get("regions") or {}
    peer_region_ids = [rid for rid in regions if rid != region_id]
    if not peer_region_ids:
        return {}, {
            "status": "unavailable",
            "reason": "no_peer_regions_for_leave_region_out",
            "period_key": period_key,
            "region_id": region_id,
            "peer_region_count": 0,
        }

    target_totals = np.zeros(len(classes), dtype=np.float64)
    source_counts: Counter[int] = Counter()
    pair_counts: Counter[tuple[int, int]] = Counter()
    for peer_id in peer_region_ids:
        peer = regions[peer_id]
        source_counts.update(Counter({int(k): int(v) for k, v in (peer.get("source_counts") or {}).items()}))
        pair_counts.update(Counter({(int(k[0]), int(k[1])): int(v) for k, v in (peer.get("pair_counts") or {}).items()}))
    for target_idx, target in enumerate(classes):
        target_totals[target_idx] = sum(pair_counts.get((int(source), int(target)), 0) for source in classes)
    target_prior = target_totals / max(1.0, float(target_totals.sum()))
    if float(target_prior.sum()) <= 0:
        target_prior = np.ones(len(classes), dtype=np.float64) / max(1, len(classes))

    priors: dict[int, np.ndarray] = {}
    peer_source_counts: dict[str, int] = {}
    smoothing_alpha = 1.0
    for source in classes:
        count = int(source_counts.get(int(source), 0))
        if count <= 0:
            continue
        raw = np.asarray([pair_counts.get((int(source), int(target)), 0) for target in classes], dtype=np.float64)
        values = (raw + smoothing_alpha * target_prior) / max(1e-12, float(raw.sum()) + smoothing_alpha)
        priors[int(source)] = values.astype(np.float32)
        peer_source_counts[str(int(source))] = count
    return priors, {
        "status": "pass" if priors else "unavailable",
        "reason": None if priors else "peer_regions_have_no_supported_source_classes",
        "period_key": period_key,
        "region_id": region_id,
        "peer_region_count": len(peer_region_ids),
        "supported_source_class_count": len(priors),
        "peer_source_counts": peer_source_counts,
        "peer_valid_cell_count": int(sum(int((regions[peer_id] or {}).get("valid_cell_count") or 0) for peer_id in peer_region_ids)),
    }


def choose_cross_region_smoothing_weights(
    *,
    model_inputs: dict[str, Any],
    base_probability: np.ndarray,
    prior_by_source: dict[int, np.ndarray],
    classes: list[int],
) -> tuple[dict[int, float], dict[str, Any]]:
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    valid = model_inputs["valid"]
    candidate_alphas = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
    weights: dict[int, float] = {}
    rows: list[dict[str, Any]] = []
    _ = base_probability
    for source in classes:
        source_mask = valid & (train_start == source)
        prior = prior_by_source.get(int(source))
        sample_count = int(source_mask.sum())
        if prior is None:
            weights[int(source)] = 0.0
            continue
        if sample_count <= 0:
            weights[int(source)] = 0.35
            rows.append(
                {
                    "source_class": int(source),
                    "selected_alpha": 32.0,
                    "selected_weight": 0.35,
                    "train_sample_count": 0,
                    "best_train_log_loss": None,
                    "reason": "no_local_source_samples_peer_prior_available",
                    "rows": [],
                }
            )
            continue
        local_counts = np.asarray(
            [int(((train_end == target) & source_mask).sum()) for target in classes],
            dtype=np.float64,
        )
        best_alpha = 0.0
        best_loss = float("inf")
        alpha_rows = []
        for alpha in candidate_alphas:
            if sample_count <= 1 and alpha <= 0.0:
                loss = float("inf")
            else:
                denom = max(1e-12, float(sample_count - 1) + float(alpha))
                numerator = np.maximum(0.0, local_counts - 1.0) + float(alpha) * prior.astype(np.float64)
                probabilities = numerator / denom
                observed = local_counts > 0
                if np.any(probabilities[observed] <= 0):
                    loss = float("inf")
                else:
                    loss = float(-np.sum(local_counts[observed] * np.log(probabilities[observed])) / max(1, sample_count))
            alpha_rows.append({"alpha": alpha, "leave_one_out_log_loss": round(loss, 6) if math.isfinite(loss) else None})
            if loss < best_loss or (math.isclose(loss, best_loss) and alpha < best_alpha):
                best_loss = loss
                best_alpha = alpha
        selected_weight = min(0.35, float(best_alpha) / max(1e-12, float(sample_count) + float(best_alpha)))
        if selected_weight < 0.01:
            selected_weight = 0.0
        weights[int(source)] = float(selected_weight)
        rows.append(
            {
                "source_class": int(source),
                "selected_alpha": float(best_alpha),
                "selected_weight": round(float(selected_weight), 6),
                "train_sample_count": sample_count,
                "best_train_log_loss": round(best_loss, 6) if math.isfinite(best_loss) else None,
                "rows": alpha_rows,
            }
        )
    positive = [weight for weight in weights.values() if weight > 0.0]
    return weights, {
        "schema": "territory_world_model.cross_region_smoothing_weight_selection.v1",
        "selection_metric": "train_period_leave_one_out_transition_log_likelihood_no_holdout_labels",
        "candidate_alphas": candidate_alphas,
        "weight_formula": "min(0.35, alpha / (local_source_count + alpha)); zeroed below 0.01",
        "selected_source_class_count": len(weights),
        "positive_weight_source_class_count": len(positive),
        "mean_selected_weight": round(float(np.mean(list(weights.values()))) if weights else 0.0, 6),
        "mean_positive_weight": round(float(np.mean(positive)) if positive else 0.0, 6),
        "source_rows": rows,
    }


def build_cross_region_smoothing_diagnostics(
    *,
    source_reports: list[dict[str, Any]],
    period_key: str,
    region_id: str,
    prior_report: dict[str, Any],
) -> dict[str, Any]:
    status_counts = Counter(str(report.get("status") or "unknown") for report in source_reports)
    smoothed = sum(1 for report in source_reports if report.get("status") == "cross_region_smoothed")
    supported = sum(
        1
        for report in source_reports
        if report.get("status") in {"cross_region_smoothed", "base_probability_calibrated_zero_weight"}
    )
    weights = [
        float(report.get("smoothing_weight") or 0.0)
        for report in source_reports
        if report.get("status") in {"cross_region_smoothed", "base_probability_calibrated_zero_weight"}
    ]
    return {
        "schema": "territory_world_model.public_landcover_training_diagnostics.v1",
        "backend": "leave_region_out_empirical_bayes_transition_smoothing",
        "status": "pass" if smoothed > 0 else "review",
        "region_id": region_id,
        "period_key": period_key,
        "source_class_count": len(source_reports),
        "fitted_source_class_count": 0,
        "fallback_source_class_count": len(source_reports) - supported,
        "pooled_fallback_source_class_count": 0,
        "hard_fallback_source_class_count": len(source_reports) - supported,
        "local_or_pooled_model_source_class_count": 0,
        "cross_region_supported_source_class_count": supported,
        "cross_region_smoothed_source_class_count": smoothed,
        "mean_smoothing_weight": round(float(np.mean(weights)) if weights else 0.0, 6),
        "status_counts": dict(status_counts),
        "source_reports": source_reports,
        "cross_region_prior_report": prior_report,
    }


def train_hierarchical_transition_probability_cube(
    model_inputs: dict[str, Any],
    *,
    include_drivers: bool,
    include_neighborhood: bool,
    pooled_fallback_weight: float | str = 1.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    shared = fit_hierarchical_transition_models(
        model_inputs,
        include_drivers=include_drivers,
        include_neighborhood=include_neighborhood,
    )
    return render_hierarchical_transition_probability_cube(
        shared,
        pooled_fallback_weight=pooled_fallback_weight,
    )


def train_hierarchical_transition_probability_cubes(
    model_inputs: dict[str, Any],
    *,
    include_drivers: bool,
    include_neighborhood: bool,
    pooled_fallback_weights: dict[str, float | str],
) -> dict[str, tuple[np.ndarray, dict[str, Any]]]:
    shared = fit_hierarchical_transition_models(
        model_inputs,
        include_drivers=include_drivers,
        include_neighborhood=include_neighborhood,
    )
    return {
        name: render_hierarchical_transition_probability_cube(shared, pooled_fallback_weight=weight)
        for name, weight in pooled_fallback_weights.items()
    }


def fit_hierarchical_transition_models(
    model_inputs: dict[str, Any],
    *,
    include_drivers: bool,
    include_neighborhood: bool,
) -> dict[str, Any]:
    try:
        from sklearn.exceptions import ConvergenceWarning
    except Exception:
        return {
            "model_inputs": model_inputs,
            "include_drivers": include_drivers,
            "include_neighborhood": include_neighborhood,
            "sklearn_unavailable": True,
        }

    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = list(model_inputs["classes"])
    features_train = source_conditioned_feature_stack(
        train_start,
        valid,
        classes,
        model_inputs["drivers"],
        include_drivers=include_drivers,
        include_neighborhood=include_neighborhood,
    )
    features_apply = source_conditioned_feature_stack(
        initial,
        valid,
        classes,
        model_inputs["drivers"],
        include_drivers=include_drivers,
        include_neighborhood=include_neighborhood,
    )
    rows, cols = np.indices(train_start.shape)
    sample_stride = 2 if int(valid.sum()) > 25000 else 1
    train_mask = valid & (((rows + cols) % sample_stride) == 0)
    global_prior = global_target_prior(train_end, valid, classes)
    pooled_model = None
    pooled_report: dict[str, Any] | None = None
    if int(train_mask.sum()) >= max(64, len(classes) * 8) and len(np.unique(train_end[train_mask])) >= 2:
        pooled_model, pooled_report = fit_transition_classifier(
            features_train[train_mask],
            train_end[train_mask].astype(int),
            source_class=-1,
            train_sample_count=int(train_mask.sum()),
            apply_cell_count=int(valid.sum()),
            convergence_warning=ConvergenceWarning,
        )
        if pooled_report is not None:
            pooled_report = {**pooled_report, "role": "pooled_fallback_model"}
    local_models: dict[int, Any] = {}
    source_reports: dict[int, dict[str, Any]] = {}
    for source in classes:
        source_train = train_mask & (train_start == source)
        source_apply = valid & (initial == source)
        observed_target_class_count = int(len(np.unique(train_end[source_train])))
        if int(source_train.sum()) < max(12, len(classes) * 4) or observed_target_class_count < 2:
            source_reports[int(source)] = {
                "source_class": int(source),
                "status": "needs_fallback",
                "train_sample_count": int(source_train.sum()),
                "apply_cell_count": int(source_apply.sum()),
                "observed_target_class_count": observed_target_class_count,
            }
            continue
        model, report = fit_transition_classifier(
            features_train[source_train],
            train_end[source_train].astype(int),
            source_class=int(source),
            train_sample_count=int(source_train.sum()),
            apply_cell_count=int(source_apply.sum()),
            convergence_warning=ConvergenceWarning,
        )
        source_reports[int(source)] = report
        if model is not None:
            local_models[int(source)] = model
    return {
        "model_inputs": model_inputs,
        "include_drivers": include_drivers,
        "include_neighborhood": include_neighborhood,
        "features_train": features_train,
        "features_apply": features_apply,
        "train_mask": train_mask,
        "sample_stride": sample_stride,
        "global_prior": global_prior,
        "pooled_model": pooled_model,
        "pooled_report": pooled_report,
        "local_models": local_models,
        "source_reports": source_reports,
        "classes": classes,
    }


def render_hierarchical_transition_probability_cube(
    shared: dict[str, Any],
    *,
    pooled_fallback_weight: float | str,
) -> tuple[np.ndarray, dict[str, Any]]:
    model_inputs = shared["model_inputs"]
    if shared.get("sklearn_unavailable"):
        return transition_prior_probability_cube(model_inputs), {
            "schema": "territory_world_model.public_landcover_training_diagnostics.v1",
            "backend": "transition_prior_probability_cube",
            "status": "fallback",
            "reason": "sklearn_unavailable",
        }
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = list(shared["classes"])
    features_apply = shared["features_apply"]
    global_prior = shared["global_prior"]
    pooled_model = shared["pooled_model"]
    pooled_report = shared["pooled_report"]
    fallback_weight, fallback_weight_report = choose_pooled_fallback_weight(
        model_inputs=model_inputs,
        pooled_model=pooled_model,
        features_train=shared["features_train"],
        train_mask=shared["train_mask"],
        global_prior=global_prior,
        classes=classes,
        requested_weight=pooled_fallback_weight,
    )
    out = np.zeros((len(classes), train_start.shape[0], train_start.shape[1]), dtype=np.float32)
    source_reports: list[dict[str, Any]] = []
    for source in classes:
        source_apply = valid & (initial == source)
        base_report = dict(shared["source_reports"].get(int(source), {}))
        model = shared["local_models"].get(int(source))
        if model is None and base_report.get("status") == "needs_fallback":
            source_train = shared["train_mask"] & (train_start == source)
            observed_target_class_count = int(len(np.unique(train_end[source_train])))
            if pooled_model is not None:
                fill_pooled_fallback_probability(
                    out=out,
                    source_apply=source_apply,
                    model=pooled_model,
                    features_apply=features_apply,
                    classes=classes,
                    prior_values=transition_prior_for_source(model_inputs, int(source), global_prior),
                    pooled_weight=fallback_weight,
                )
                source_reports.append(
                    {
                        **base_report,
                        "status": "pooled_fallback",
                        "pooled_fallback_weight": fallback_weight,
                        "observed_target_class_count": observed_target_class_count,
                    }
                )
            else:
                values = transition_prior_for_source(model_inputs, int(source), global_prior)
                out[:, source_apply] = values[:, None]
                source_reports.append(
                    {
                        **base_report,
                        "status": "fallback_transition_prior",
                        "observed_target_class_count": observed_target_class_count,
                    }
                )
            continue
        if model is None and pooled_model is not None:
            fill_pooled_fallback_probability(
                out=out,
                source_apply=source_apply,
                model=pooled_model,
                features_apply=features_apply,
                classes=classes,
                prior_values=transition_prior_for_source(model_inputs, int(source), global_prior),
                pooled_weight=fallback_weight,
            )
            source_reports.append(
                {
                    **base_report,
                    "status": "pooled_fallback_after_local_failure",
                    "local_failure_status": base_report.get("status"),
                    "pooled_fallback_weight": fallback_weight,
                }
            )
            continue
        if model is None:
            values = transition_prior_for_source(model_inputs, int(source), global_prior)
            out[:, source_apply] = values[:, None]
            source_reports.append(base_report)
            continue
        source_reports.append(base_report)
        fill_probability_from_model(
            out=out,
            source_apply=source_apply,
            model=model,
            features_apply=features_apply,
            classes=classes,
        )
    out[:, ~valid] = 0.0
    return out, build_training_diagnostics(
        include_drivers=shared["include_drivers"],
        include_neighborhood=shared["include_neighborhood"],
        sample_stride=shared["sample_stride"],
        source_reports=source_reports,
        backend="hierarchical_pooled_per_source_multinomial_logit",
        pooled_model_report=pooled_report,
        fallback_weight_report=fallback_weight_report,
    )


def choose_pooled_fallback_weight(
    *,
    model_inputs: dict[str, Any],
    pooled_model: Any | None,
    features_train: np.ndarray,
    train_mask: np.ndarray,
    global_prior: np.ndarray,
    classes: list[int],
    requested_weight: float | str,
) -> tuple[float, dict[str, Any]]:
    if requested_weight != "auto":
        weight = float(requested_weight)
        return max(0.0, min(1.0, weight)), {
            "mode": "fixed",
            "pooled_fallback_weight": max(0.0, min(1.0, weight)),
        }
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    valid = model_inputs["valid"]
    if pooled_model is None:
        return 0.0, {"mode": "auto", "pooled_fallback_weight": 0.0, "reason": "pooled_model_unavailable"}
    fallback_mask = np.zeros(train_start.shape, dtype=bool)
    for source in classes:
        source_train = train_mask & (train_start == source)
        if int(source_train.sum()) < max(12, len(classes) * 4) or len(np.unique(train_end[source_train])) < 2:
            fallback_mask |= source_train
    if int(fallback_mask.sum()) < max(12, len(classes)):
        fallback_mask = train_mask
    pooled_prob = probability_from_model(
        model=pooled_model,
        features=features_train[fallback_mask],
        classes=classes,
    )
    prior_prob = prior_probability_for_cells(
        model_inputs=model_inputs,
        source_values=train_start[fallback_mask].astype(int),
        global_prior=global_prior,
        classes=classes,
    )
    target = train_end[fallback_mask].astype(int)
    weights = [0.0, 0.25, 0.5, 0.75, 1.0]
    rows = []
    best_weight = 0.0
    best_score = -1.0
    for weight in weights:
        mixed = weight * pooled_prob + (1.0 - weight) * prior_prob
        pred = np.asarray(classes, dtype=np.int16)[np.argmax(mixed, axis=1)]
        score = float(np.mean(pred == target)) if target.size else 0.0
        rows.append({"pooled_weight": weight, "train_top1_accuracy": round(score, 6)})
        if score > best_score or (math.isclose(score, best_score) and weight < best_weight):
            best_score = score
            best_weight = weight
    return best_weight, {
        "mode": "auto",
        "pooled_fallback_weight": best_weight,
        "calibration_sample_count": int(target.size),
        "selection_metric": "train_top1_accuracy_on_sparse_source_or_train_cells",
        "rows": rows,
    }


def probability_from_model(*, model: Any, features: np.ndarray, classes: list[int]) -> np.ndarray:
    probs = model.predict_proba(features)
    estimator = model.named_steps["logisticregression"]
    class_to_col = {int(cls): idx for idx, cls in enumerate(estimator.classes_)}
    out = np.zeros((features.shape[0], len(classes)), dtype=np.float32)
    for target_idx, target in enumerate(classes):
        col = class_to_col.get(int(target))
        if col is not None:
            out[:, target_idx] = probs[:, col]
    totals = out.sum(axis=1, keepdims=True)
    np.divide(out, totals, out=out, where=totals > 0)
    return out


def prior_probability_for_cells(
    *,
    model_inputs: dict[str, Any],
    source_values: np.ndarray,
    global_prior: np.ndarray,
    classes: list[int],
) -> np.ndarray:
    out = np.zeros((source_values.shape[0], len(classes)), dtype=np.float32)
    cache: dict[int, np.ndarray] = {}
    for source in np.unique(source_values.astype(int)):
        cache[int(source)] = transition_prior_for_source(model_inputs, int(source), global_prior)
    for idx, source in enumerate(source_values.astype(int)):
        out[idx, :] = cache.get(int(source), global_prior)
    return out


def fill_pooled_fallback_probability(
    *,
    out: np.ndarray,
    source_apply: np.ndarray,
    model: Any,
    features_apply: np.ndarray,
    classes: list[int],
    prior_values: np.ndarray,
    pooled_weight: float,
) -> None:
    if int(source_apply.sum()) <= 0:
        return
    pooled = probability_from_model(model=model, features=features_apply[source_apply], classes=classes)
    prior = np.repeat(prior_values[None, :], pooled.shape[0], axis=0)
    mixed = pooled_weight * pooled + (1.0 - pooled_weight) * prior
    totals = mixed.sum(axis=1, keepdims=True)
    np.divide(mixed, totals, out=mixed, where=totals > 0)
    out[:, source_apply] = mixed.T


def fill_probability_from_model(
    *,
    out: np.ndarray,
    source_apply: np.ndarray,
    model: Any,
    features_apply: np.ndarray,
    classes: list[int],
) -> None:
    if int(source_apply.sum()) <= 0:
        return
    probs = model.predict_proba(features_apply[source_apply])
    estimator = model.named_steps["logisticregression"]
    class_to_col = {int(cls): idx for idx, cls in enumerate(estimator.classes_)}
    for target_idx, target in enumerate(classes):
        col = class_to_col.get(int(target))
        if col is not None:
            out[target_idx, source_apply] = probs[:, col]


def fit_transition_classifier(
    x_train: np.ndarray,
    y_train: np.ndarray,
    *,
    source_class: int,
    train_sample_count: int,
    apply_cell_count: int,
    convergence_warning: type[Warning],
) -> tuple[Any | None, dict[str, Any]]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    attempts = [
        {"solver": "lbfgs", "max_iter": 1200, "class_weight": "balanced", "C": 0.8},
        {"solver": "newton-cg", "max_iter": 900, "class_weight": "balanced", "C": 0.8},
        {"solver": "saga", "max_iter": 1600, "class_weight": "balanced", "C": 0.5},
    ]
    warnings_seen: list[str] = []
    for attempt in attempts:
        model = make_pipeline(
            StandardScaler(),
            LogisticRegression(
                class_weight=attempt["class_weight"],
                max_iter=int(attempt["max_iter"]),
                random_state=0,
                solver=str(attempt["solver"]),
                C=float(attempt["C"]),
                n_jobs=1,
            ),
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", convergence_warning)
            try:
                model.fit(x_train, y_train)
            except Exception as exc:  # noqa: BLE001
                warnings_seen.append(f"{attempt['solver']}: {type(exc).__name__}: {exc}")
                continue
        convergence_warnings = [item for item in caught if issubclass(item.category, convergence_warning)]
        if convergence_warnings:
            warnings_seen.extend([f"{attempt['solver']}: {str(item.message).splitlines()[0]}" for item in convergence_warnings[:2]])
            continue
        estimator = model.named_steps["logisticregression"]
        return model, {
            "source_class": source_class,
            "status": "fit",
            "solver": attempt["solver"],
            "max_iter": attempt["max_iter"],
            "class_weight": attempt["class_weight"],
            "regularization_c": attempt["C"],
            "train_sample_count": train_sample_count,
            "apply_cell_count": apply_cell_count,
            "observed_target_class_count": int(len(np.unique(y_train))),
            "target_classes": [int(value) for value in estimator.classes_],
            "n_iter_max": int(np.max(estimator.n_iter_)) if hasattr(estimator, "n_iter_") else None,
            "fallback_warnings": warnings_seen,
        }
    return None, {
        "source_class": source_class,
        "status": "fallback_transition_prior",
        "train_sample_count": train_sample_count,
        "apply_cell_count": apply_cell_count,
        "observed_target_class_count": int(len(np.unique(y_train))),
        "fallback_warnings": warnings_seen,
    }


def build_training_diagnostics(
    *,
    include_drivers: bool,
    include_neighborhood: bool,
    sample_stride: int,
    source_reports: list[dict[str, Any]],
    backend: str = "per_source_multinomial_logit",
    pooled_model_report: dict[str, Any] | None = None,
    fallback_weight_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status_counts = Counter(str(report.get("status")) for report in source_reports)
    fitted = sum(1 for report in source_reports if report.get("status") == "fit")
    pooled_fallback = sum(1 for report in source_reports if str(report.get("status") or "").startswith("pooled_fallback"))
    fallback = len(source_reports) - fitted
    hard_fallback = fallback - pooled_fallback
    diagnostics = {
        "schema": "territory_world_model.public_landcover_training_diagnostics.v1",
        "backend": backend,
        "status": "pass" if fallback == 0 else "review",
        "include_drivers": include_drivers,
        "include_neighborhood": include_neighborhood,
        "sample_stride": int(sample_stride),
        "source_class_count": len(source_reports),
        "fitted_source_class_count": fitted,
        "fallback_source_class_count": fallback,
        "pooled_fallback_source_class_count": pooled_fallback,
        "hard_fallback_source_class_count": hard_fallback,
        "local_or_pooled_model_source_class_count": fitted + pooled_fallback,
        "status_counts": dict(status_counts),
        "source_reports": source_reports,
    }
    if pooled_model_report is not None:
        diagnostics["pooled_model_report"] = pooled_model_report
    if fallback_weight_report is not None:
        diagnostics["fallback_weight_report"] = fallback_weight_report
    return diagnostics


def transition_prior_for_source(model_inputs: dict[str, Any], source: int, global_prior: np.ndarray) -> np.ndarray:
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    valid = model_inputs["valid"]
    classes = list(model_inputs["classes"])
    pair_counts: Counter[tuple[int, int]] = Counter(zip(train_start[valid].astype(int), train_end[valid].astype(int)))
    source_count = int((valid & (train_start == source)).sum())
    if source_count <= 0:
        return global_prior
    values = np.asarray([pair_counts.get((source, target), 0) / max(1, source_count) for target in classes], dtype=np.float32)
    if float(values.sum()) <= 0:
        return global_prior
    return values / float(values.sum())


def transition_prior_probability_cube(model_inputs: dict[str, Any]) -> np.ndarray:
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = list(model_inputs["classes"])
    pair_counts: Counter[tuple[int, int]] = Counter(zip(train_start[valid].astype(int), train_end[valid].astype(int)))
    source_counts = Counter(train_start[valid].astype(int).tolist())
    global_prior = global_target_prior(train_end, valid, classes)
    out = np.zeros((len(classes), train_start.shape[0], train_start.shape[1]), dtype=np.float32)
    for source in classes:
        source_apply = valid & (initial == source)
        if source_counts.get(source, 0) <= 0:
            out[:, source_apply] = global_prior[:, None]
            continue
        values = np.asarray([pair_counts.get((source, target), 0) / max(1, source_counts[source]) for target in classes], dtype=np.float32)
        if float(values.sum()) <= 0:
            values = global_prior
        else:
            values = values / float(values.sum())
        out[:, source_apply] = values[:, None]
    out[:, ~valid] = 0.0
    return out


def global_target_prior(arr: np.ndarray, valid: np.ndarray, classes: list[int]) -> np.ndarray:
    counts = class_counts(arr, valid, classes)
    values = np.asarray([counts[cls] for cls in classes], dtype=np.float32)
    total = float(values.sum())
    if total <= 0:
        return np.ones(len(classes), dtype=np.float32) / max(1, len(classes))
    return values / total


def feature_stack(
    arr: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    drivers: dict[str, np.ndarray],
    *,
    include_drivers: bool,
    include_neighborhood: bool,
) -> np.ndarray:
    height, width = arr.shape
    row = np.repeat(np.arange(height, dtype=np.float32)[:, None], width, axis=1) / max(1, height - 1)
    col = np.repeat(np.arange(width, dtype=np.float32)[None, :], height, axis=0) / max(1, width - 1)
    raw = [row, col, stable_cell_hash(arr.shape, 811)]
    if include_drivers:
        for name in sorted(drivers):
            raw.append(normalize_01(drivers[name]))
    if include_neighborhood:
        for cls in classes:
            raw.append(neighbor_density(arr, cls, valid))
    stack = np.stack(raw, axis=-1).astype(np.float32)
    stack[~np.isfinite(stack)] = 0.0
    return stack


def source_conditioned_feature_stack(
    arr: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    drivers: dict[str, np.ndarray],
    *,
    include_drivers: bool,
    include_neighborhood: bool,
) -> np.ndarray:
    base = feature_stack(
        arr,
        valid,
        classes,
        drivers,
        include_drivers=include_drivers,
        include_neighborhood=include_neighborhood,
    )
    source_one_hot = np.stack([(arr == cls).astype(np.float32) for cls in classes], axis=-1)
    stack = np.concatenate([base, source_one_hot], axis=-1).astype(np.float32)
    stack[~np.isfinite(stack)] = 0.0
    return stack


def transition_score_cube(
    model_inputs: dict[str, Any],
    probability: np.ndarray,
    *,
    include_neighborhood: bool,
    include_prior: bool,
) -> np.ndarray:
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = list(model_inputs["classes"])
    prior = transition_prior_score_fields(model_inputs)
    scores: list[np.ndarray] = []
    for idx, target in enumerate(classes):
        score = (
            0.74 * normalize_01(probability[idx])
            - 0.10 * (initial == target).astype(np.float32)
            + 0.01 * stable_cell_hash(initial.shape, 911 + idx)
        )
        if include_neighborhood:
            score = score + 0.16 * neighbor_density(initial, target, valid)
        if include_prior:
            score = score + 0.08 * prior[target]
        score[~valid] = -1e9
        scores.append(score.astype(np.float32))
    return np.stack(scores)


def transition_prior_score_fields(model_inputs: dict[str, Any]) -> dict[int, np.ndarray]:
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = list(model_inputs["classes"])
    pair_counts: Counter[tuple[int, int]] = Counter(zip(train_start[valid].astype(int), train_end[valid].astype(int)))
    source_counts = Counter(train_start[valid].astype(int).tolist())
    fields: dict[int, np.ndarray] = {}
    for target in classes:
        arr = np.zeros(initial.shape, dtype=np.float32)
        for source in classes:
            arr[initial == source] = pair_counts.get((source, target), 0) / max(1, source_counts.get(source, 0))
        fields[target] = normalize_01(arr)
    return fields


def allocate_markov_projection(model_inputs: dict[str, Any], target_counts: dict[int, int]) -> np.ndarray:
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = list(model_inputs["classes"])
    pair_counts: Counter[tuple[int, int]] = Counter(zip(train_start[valid].astype(int), train_end[valid].astype(int)))
    source_counts = Counter(train_start[valid].astype(int).tolist())
    current_counts = class_counts(initial, valid, classes)
    pred = initial.copy()
    reserved = np.zeros(initial.shape, dtype=bool)
    stable = stable_cell_hash(initial.shape, 613)
    deficits = {cls: max(0, int(target_counts[cls]) - int(current_counts.get(cls, 0))) for cls in classes}
    surpluses = {cls: max(0, int(current_counts.get(cls, 0)) - int(target_counts[cls])) for cls in classes}
    for target, need in sorted(deficits.items(), key=lambda item: -item[1]):
        remaining = int(need)
        source_order = sorted(
            [cls for cls, surplus in surpluses.items() if surplus > 0 and cls != target],
            key=lambda source: pair_counts.get((source, target), 0) / max(1, source_counts.get(source, 0)),
            reverse=True,
        )
        for source in source_order:
            if remaining <= 0:
                break
            rows, cols = np.where(valid & (~reserved) & (pred == source))
            if rows.size == 0:
                continue
            take = min(remaining, surpluses[source], rows.size)
            selected = np.argpartition(stable[rows, cols], -take)[-take:]
            pred[rows[selected], cols[selected]] = target
            reserved[rows[selected], cols[selected]] = True
            surpluses[source] -= int(take)
            remaining -= int(take)
    pred[~valid] = 0
    return pred


def allocate_score_projection(model_inputs: dict[str, Any], target_counts: dict[int, int], score: np.ndarray) -> np.ndarray:
    classes = list(model_inputs["classes"])
    valid = model_inputs["valid"]
    initial = model_inputs["initial"]
    class_to_idx = {cls: idx for idx, cls in enumerate(classes)}
    pred = initial.copy()
    reserved = np.zeros(initial.shape, dtype=bool)
    current_counts = class_counts(initial, valid, classes)
    deficits = {cls: max(0, int(target_counts[cls]) - int(current_counts[cls])) for cls in classes}
    surpluses = {cls: max(0, int(current_counts[cls]) - int(target_counts[cls])) for cls in classes}
    for target in sorted(classes, key=lambda cls: deficits[cls], reverse=True):
        remaining = int(deficits[target])
        if remaining <= 0:
            continue
        candidates: list[tuple[np.ndarray, np.ndarray, np.ndarray, int]] = []
        for source in classes:
            if source == target or surpluses[source] <= 0:
                continue
            rows, cols = np.where(valid & (~reserved) & (pred == source) & (score[class_to_idx[target]] > -1e8))
            if rows.size == 0:
                continue
            values = score[class_to_idx[target]][rows, cols] - score[class_to_idx[source]][rows, cols]
            candidates.append((rows, cols, values, source))
        if not candidates:
            continue
        rows = np.concatenate([item[0] for item in candidates])
        cols = np.concatenate([item[1] for item in candidates])
        values = np.concatenate([item[2] for item in candidates])
        sources = np.concatenate([np.full(item[0].shape, item[3], dtype=np.int16) for item in candidates])
        order = np.argsort(values)[::-1]
        for idx in order:
            if remaining <= 0:
                break
            source = int(sources[idx])
            if surpluses[source] <= 0:
                continue
            row = int(rows[idx])
            col = int(cols[idx])
            if reserved[row, col] or pred[row, col] != source:
                continue
            pred[row, col] = target
            reserved[row, col] = True
            surpluses[source] -= 1
            remaining -= 1
    pred[~valid] = 0
    pred = balance_to_target_counts(pred=pred, initial=initial, valid=valid, classes=classes, target_counts=target_counts, score=score)
    pred[~valid] = 0
    return pred


def allocate_free_score_assignment(model_inputs: dict[str, Any], score: np.ndarray) -> np.ndarray:
    classes = list(model_inputs["classes"])
    valid = model_inputs["valid"]
    initial = model_inputs["initial"]
    class_to_idx = {idx: cls for idx, cls in enumerate(classes)}
    best_idx = np.argmax(score, axis=0)
    pred = initial.copy()
    for idx, cls in class_to_idx.items():
        pred[valid & (best_idx == idx) & (score[idx] > -1e8)] = cls
    impossible = valid & (np.max(score, axis=0) < -1e8)
    pred[impossible] = initial[impossible]
    pred[~valid] = 0
    return pred


def balance_to_target_counts(
    *,
    pred: np.ndarray,
    initial: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    target_counts: dict[int, int],
    score: np.ndarray,
) -> np.ndarray:
    class_to_idx = {cls: idx for idx, cls in enumerate(classes)}
    pred = pred.copy()
    for _ in range(120):
        counts = class_counts(pred, valid, classes)
        over = [cls for cls in classes if counts[cls] > int(target_counts[cls])]
        under = [cls for cls in classes if counts[cls] < int(target_counts[cls])]
        if not over and not under:
            break
        best: tuple[float, int, int, np.ndarray, np.ndarray, np.ndarray] | None = None
        for source in over:
            source_mask = valid & (pred == source)
            for target in under:
                target_score = score[class_to_idx[target]]
                source_score = score[class_to_idx[source]]
                rows, cols = np.where(source_mask & (target_score > -1e8))
                if rows.size == 0:
                    continue
                delta = target_score[rows, cols] - source_score[rows, cols] - 0.02 * (initial[rows, cols] == target)
                option = (float(np.max(delta)), source, target, rows, cols, delta)
                if best is None or option[0] > best[0]:
                    best = option
        if best is None:
            break
        _, source, target, rows, cols, delta = best
        counts = class_counts(pred, valid, classes)
        take = min(counts[source] - int(target_counts[source]), int(target_counts[target]) - counts[target], rows.size)
        if take <= 0:
            break
        selected = np.argpartition(delta, -take)[-take:]
        pred[rows[selected], cols[selected]] = target
    return pred


def build_ablation_summary(metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    main = "twm_independent_transition_forecast_demand"
    ablations = [
        "twm_ablation_no_drivers_forecast_demand",
        "twm_ablation_no_neighborhood_forecast_demand",
        "twm_ablation_no_transition_prior_forecast_demand",
        "twm_ablation_no_demand_projection",
    ]
    if main not in metrics:
        return {"status": "missing_main_candidate"}
    main_metric = metrics[main]
    rows = []
    for name in ablations:
        metric = metrics.get(name)
        if metric is None:
            continue
        rows.append(
            {
                "candidate_id": name,
                "change_fom_delta_vs_full": round(float(metric["change_fom"]) - float(main_metric["change_fom"]), 6),
                "overall_accuracy_delta_vs_full": round(float(metric["overall_accuracy"]) - float(main_metric["overall_accuracy"]), 6),
                "change_f1_delta_vs_full": round(float(metric["change_f1"]) - float(main_metric["change_f1"]), 6),
                "target_demand_abs_error_delta_vs_full": int(metric["target_total_demand_abs_error"])
                - int(main_metric["target_total_demand_abs_error"]),
                "predicted_change_delta_vs_full": int(metric["predicted_change_count"]) - int(main_metric["predicted_change_count"]),
            }
        )
    harmful_by_fom = [row for row in rows if row["change_fom_delta_vs_full"] < 0]
    helpful_by_fom = [row for row in rows if row["change_fom_delta_vs_full"] > 0]
    return {
        "status": "pass",
        "full_candidate_id": main,
        "rows": rows,
        "components_with_positive_change_fom_contribution": [
            row["candidate_id"].replace("twm_ablation_no_", "").replace("_forecast_demand", "")
            for row in harmful_by_fom
        ],
        "ablations_with_higher_change_fom_than_full": [row["candidate_id"] for row in helpful_by_fom],
        "interpretation": "Negative ablation delta means the removed component improved the full candidate on that metric in this case.",
    }


def pixel_metrics(
    *,
    prediction: np.ndarray,
    actual: np.ndarray,
    initial: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    cell_area_ha: float,
    target_counts: dict[int, int],
) -> dict[str, Any]:
    pred = prediction[valid].astype(int)
    truth = actual[valid].astype(int)
    base = initial[valid].astype(int)
    n = int(valid.sum())
    correct = int((pred == truth).sum())
    pred_counts = Counter(pred.tolist())
    truth_counts = Counter(truth.tolist())
    po = correct / max(1, n)
    pe = sum(pred_counts.get(cls, 0) * truth_counts.get(cls, 0) for cls in classes) / float(max(1, n * n))
    kappa = (po - pe) / max(1e-12, 1.0 - pe)
    pred_change = pred != base
    actual_change = truth != base
    tp = int((pred_change & actual_change).sum())
    fp = int((pred_change & ~actual_change).sum())
    fn = int((~pred_change & actual_change).sum())
    change_precision = tp / max(1, tp + fp)
    change_recall = tp / max(1, tp + fn)
    per_class_f1: dict[str, float] = {}
    for cls in classes:
        cls_tp = int(((pred == cls) & (truth == cls)).sum())
        cls_fp = int(((pred == cls) & (truth != cls)).sum())
        cls_fn = int(((pred != cls) & (truth == cls)).sum())
        precision = cls_tp / max(1, cls_tp + cls_fp)
        recall = cls_tp / max(1, cls_tp + cls_fn)
        per_class_f1[str(cls)] = round(harmonic(precision, recall), 6)
    demand_abs_error = {str(cls): abs(int(pred_counts.get(cls, 0)) - int(target_counts.get(cls, 0))) for cls in classes}
    oracle_abs_error = {str(cls): abs(int(pred_counts.get(cls, 0)) - int(truth_counts.get(cls, 0))) for cls in classes}
    return {
        "schema": "territory_world_model.public_landcover_pixel_metric.v1",
        "valid_cell_count": n,
        "overall_accuracy": round(po, 6),
        "kappa": round(kappa, 6),
        "correct_cell_count": correct,
        "predicted_change_count": int(pred_change.sum()),
        "actual_change_count": int(actual_change.sum()),
        "change_hit_count": tp,
        "change_false_alarm_count": fp,
        "change_miss_count": fn,
        "change_precision": round(change_precision, 6),
        "change_recall": round(change_recall, 6),
        "change_f1": round(harmonic(change_precision, change_recall), 6),
        "change_fom": round(tp / max(1, tp + fp + fn), 6),
        "predicted_changed_area_ha": round(float(pred_change.sum()) * cell_area_ha, 4),
        "actual_changed_area_ha": round(float(actual_change.sum()) * cell_area_ha, 4),
        "target_demand_abs_error": demand_abs_error,
        "target_total_demand_abs_error": int(sum(demand_abs_error.values())),
        "oracle_total_demand_abs_error": int(sum(oracle_abs_error.values())),
        "macro_f1": round(float(np.mean(list(per_class_f1.values()))) if per_class_f1 else 0.0, 6),
        "per_class_f1": per_class_f1,
    }


def aggregate_experiments(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for experiment in experiments:
        for candidate_id, metric in experiment["metrics"].items():
            rows.setdefault(candidate_id, []).append(metric)
    aggregate = {}
    for candidate_id, metrics in rows.items():
        aggregate[candidate_id] = {
            "case_count": len(metrics),
            "mean_overall_accuracy": round(float(np.mean([m["overall_accuracy"] for m in metrics])), 6),
            "mean_kappa": round(float(np.mean([m["kappa"] for m in metrics])), 6),
            "mean_change_fom": round(float(np.mean([m["change_fom"] for m in metrics])), 6),
            "mean_change_f1": round(float(np.mean([m["change_f1"] for m in metrics])), 6),
            "mean_macro_f1": round(float(np.mean([m["macro_f1"] for m in metrics])), 6),
            "total_target_demand_abs_error": int(sum(m["target_total_demand_abs_error"] for m in metrics)),
            "total_oracle_demand_abs_error": int(sum(m["oracle_total_demand_abs_error"] for m in metrics)),
        }
    ranking = sorted(
        [
            {
                "candidate_id": candidate_id,
                **payload,
            }
            for candidate_id, payload in aggregate.items()
        ],
        key=lambda item: (item["mean_change_fom"], item["mean_overall_accuracy"]),
        reverse=True,
    )
    return {
        "aggregate_by_candidate": aggregate,
        "ranking_by_mean_change_fom": ranking,
        "best_candidate_by_mean_change_fom": ranking[0]["candidate_id"] if ranking else None,
        "aggregate_component_diagnostics": build_aggregate_component_diagnostics(aggregate),
        "training_diagnostics_by_candidate": aggregate_training_diagnostics(experiments),
    }


def build_aggregate_component_diagnostics(aggregate: dict[str, dict[str, Any]]) -> dict[str, Any]:
    full_id = "twm_independent_transition_forecast_demand"
    full = aggregate.get(full_id)
    if not full:
        return {"status": "missing_full_candidate", "full_candidate_id": full_id}
    comparisons = [
        ("markov_transition_projection", "transition_surface_vs_markov"),
        ("twm_hierarchical_transition_forecast_demand", "hierarchical_pooling_candidate"),
        ("twm_calibrated_hierarchical_transition_forecast_demand", "calibrated_hierarchical_pooling_candidate"),
        ("twm_cross_region_smoothed_transition_forecast_demand", "cross_region_transition_smoothing_candidate"),
        ("twm_ablation_no_drivers_forecast_demand", "external_drivers"),
        ("twm_ablation_no_neighborhood_forecast_demand", "neighborhood_context"),
        ("twm_ablation_no_transition_prior_forecast_demand", "transition_prior"),
        ("twm_ablation_no_demand_projection", "demand_projection_constraint"),
    ]
    rows: list[dict[str, Any]] = []
    for candidate_id, component in comparisons:
        candidate = aggregate.get(candidate_id)
        if not candidate:
            continue
        rows.append(
            {
                "component": component,
                "comparison_candidate_id": candidate_id,
                "change_fom_delta_full_minus_comparison": round(
                    float(full["mean_change_fom"]) - float(candidate["mean_change_fom"]), 6
                ),
                "overall_accuracy_delta_full_minus_comparison": round(
                    float(full["mean_overall_accuracy"]) - float(candidate["mean_overall_accuracy"]), 6
                ),
                "change_f1_delta_full_minus_comparison": round(
                    float(full["mean_change_f1"]) - float(candidate["mean_change_f1"]), 6
                ),
                "target_demand_abs_error_delta_full_minus_comparison": int(full["total_target_demand_abs_error"])
                - int(candidate["total_target_demand_abs_error"]),
            }
        )
    return {
        "status": "pass",
        "full_candidate_id": full_id,
        "rows": rows,
        "positive_change_fom_components": [
            row["component"]
            for row in rows
            if row["component"] != "demand_projection_constraint"
            and row["change_fom_delta_full_minus_comparison"] > 0
        ],
        "non_positive_change_fom_components": [
            row["component"]
            for row in rows
            if row["component"] != "demand_projection_constraint"
            and row["change_fom_delta_full_minus_comparison"] <= 0
        ],
        "demand_projection_required_for_valid_forecast": any(
            row["component"] == "demand_projection_constraint"
            and row["target_demand_abs_error_delta_full_minus_comparison"] < 0
            for row in rows
        ),
        "interpretation": (
            "Positive delta means the full forecast-demand TWM candidate improves over the comparison "
            "on the aggregate metric. The no-demand comparison is diagnostic only because it can improve "
            "change detection while violating class-total demand."
        ),
    }


def aggregate_training_diagnostics(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    aggregated: dict[str, Any] = {}
    for experiment in experiments:
        for candidate_id, metadata in (experiment.get("candidate_metadata") or {}).items():
            diagnostics = metadata.get("training_diagnostics")
            if not diagnostics:
                continue
            row = aggregated.setdefault(
                candidate_id,
                {
                    "case_count": 0,
                    "pass_case_count": 0,
                    "review_case_count": 0,
                    "source_class_count": 0,
                    "fitted_source_class_count": 0,
                    "fallback_source_class_count": 0,
                    "pooled_fallback_source_class_count": 0,
                    "hard_fallback_source_class_count": 0,
                    "local_or_pooled_model_source_class_count": 0,
                    "pooled_fallback_weight_sum": 0.0,
                    "pooled_fallback_weight_case_count": 0,
                    "smoothing_weight_sum": 0.0,
                    "smoothing_weight_case_count": 0,
                    "cross_region_supported_source_class_count": 0,
                    "cross_region_smoothed_source_class_count": 0,
                    "solver_counts": {},
                    "source_status_counts": {},
                },
            )
            row["case_count"] += 1
            status = str(diagnostics.get("status") or "")
            if status == "pass":
                row["pass_case_count"] += 1
            elif status == "review":
                row["review_case_count"] += 1
            row["source_class_count"] += int(diagnostics.get("source_class_count") or 0)
            row["fitted_source_class_count"] += int(diagnostics.get("fitted_source_class_count") or 0)
            row["fallback_source_class_count"] += int(diagnostics.get("fallback_source_class_count") or 0)
            row["pooled_fallback_source_class_count"] += int(diagnostics.get("pooled_fallback_source_class_count") or 0)
            row["hard_fallback_source_class_count"] += int(diagnostics.get("hard_fallback_source_class_count") or 0)
            row["local_or_pooled_model_source_class_count"] += int(diagnostics.get("local_or_pooled_model_source_class_count") or 0)
            fallback_weight_report = diagnostics.get("fallback_weight_report") or {}
            if "pooled_fallback_weight" in fallback_weight_report:
                row["pooled_fallback_weight_sum"] += float(fallback_weight_report["pooled_fallback_weight"])
                row["pooled_fallback_weight_case_count"] += 1
            if "mean_smoothing_weight" in diagnostics:
                row["smoothing_weight_sum"] += float(diagnostics.get("mean_smoothing_weight") or 0.0)
                row["smoothing_weight_case_count"] += 1
            row["cross_region_supported_source_class_count"] += int(
                diagnostics.get("cross_region_supported_source_class_count") or 0
            )
            row["cross_region_smoothed_source_class_count"] += int(
                diagnostics.get("cross_region_smoothed_source_class_count") or 0
            )
            for source_report in diagnostics.get("source_reports") or []:
                source_status = str(source_report.get("status") or "unknown")
                row["source_status_counts"][source_status] = row["source_status_counts"].get(source_status, 0) + 1
                solver = source_report.get("solver")
                if solver:
                    row["solver_counts"][str(solver)] = row["solver_counts"].get(str(solver), 0) + 1
    for row in aggregated.values():
        total = max(1, int(row["source_class_count"]))
        row["fallback_source_class_rate"] = round(float(row["fallback_source_class_count"]) / total, 6)
        row["pooled_fallback_source_class_rate"] = round(float(row["pooled_fallback_source_class_count"]) / total, 6)
        row["hard_fallback_source_class_rate"] = round(float(row["hard_fallback_source_class_count"]) / total, 6)
        row["local_or_pooled_model_source_class_rate"] = round(float(row["local_or_pooled_model_source_class_count"]) / total, 6)
        weight_cases = int(row["pooled_fallback_weight_case_count"])
        row["mean_pooled_fallback_weight"] = round(
            float(row["pooled_fallback_weight_sum"]) / max(1, weight_cases),
            6,
        )
        smoothing_cases = int(row["smoothing_weight_case_count"])
        row["mean_smoothing_weight"] = round(
            float(row["smoothing_weight_sum"]) / max(1, smoothing_cases),
            6,
        )
        row["cross_region_supported_source_class_rate"] = round(
            float(row["cross_region_supported_source_class_count"]) / total,
            6,
        )
        row["cross_region_smoothed_source_class_rate"] = round(
            float(row["cross_region_smoothed_source_class_count"]) / total,
            6,
        )
    return aggregated


def region_profile(region: BenchmarkRegion) -> dict[str, Any]:
    return {
        "region_id": region.region_id,
        "years": [frame.year for frame in region.frames],
        "shape": list(region.frames[0].array.shape),
        "classes": {str(key): value for key, value in region.class_labels.items()},
        "cell_area_ha": region.cell_area_ha,
        "driver_layers": sorted(region.drivers),
        "source": region.source,
    }


def render_assets(
    *,
    asset_dir: Path,
    regions: list[BenchmarkRegion],
    experiments: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap

    metrics_path = asset_dir / "twm_public_landcover_benchmark_metrics.png"
    ranking = summary.get("ranking_by_mean_change_fom") or []
    names = [item["candidate_id"] for item in ranking]
    x = np.arange(len(names))
    fig_width = max(10.5, 1.35 * max(1, len(names)))
    fig, ax = plt.subplots(figsize=(fig_width, 4.8), constrained_layout=True)
    width = 0.28
    ax.bar(x - width, [summary["aggregate_by_candidate"][name]["mean_overall_accuracy"] for name in names], width, label="OA", color="#37474f")
    ax.bar(x, [summary["aggregate_by_candidate"][name]["mean_change_fom"] for name in names], width, label="Change FoM", color="#b71c1c")
    ax.bar(x + width, [summary["aggregate_by_candidate"][name]["mean_macro_f1"] for name in names], width, label="Macro F1", color="#2e7d32")
    ax.set_ylim(0, 1.02)
    ax.set_xticks(x)
    ax.set_xticklabels([name.replace("_", "\n") for name in names], fontsize=8)
    ax.grid(axis="y", color="#e0e0e0", linewidth=0.8)
    ax.legend(frameon=False, ncol=3)
    fig.savefig(metrics_path, bbox_inches="tight", dpi=180)
    plt.close(fig)

    first_case = experiments[0]
    region = next(item for item in regions if item.region_id == first_case["region_id"])
    years = [int(value) for value in first_case["case_id"].split("_")[-3:]]
    frame_by_year = {frame.year: frame for frame in region.frames}
    class_values = list(region.classes)
    max_class = max(class_values)
    colors = ["#f1f1ec", "#f2c94c", "#2f7d32", "#7cb342", "#2f80ed", "#c0392b", "#8d6e63", "#9e9e9e", "#6a5acd", "#00a6a6"]
    if max_class + 1 > len(colors):
        colors.extend(["#cccccc"] * (max_class + 1 - len(colors)))
    cmap = ListedColormap(colors[: max_class + 1])
    norm = BoundaryNorm(np.arange(-0.5, max_class + 1.5, 1), cmap.N)
    predictions = rebuild_case_predictions(region, years)
    map_items = [
        (f"Train start {years[0]}", frame_by_year[years[0]].array),
        (f"Initial {years[1]}", frame_by_year[years[1]].array),
        (f"Truth {years[2]}", frame_by_year[years[2]].array),
        ("TWM forecast", predictions["twm_independent_transition_forecast_demand"]),
        ("TWM oracle", predictions["twm_independent_transition_oracle_demand"]),
    ]
    fig, axes = plt.subplots(1, len(map_items), figsize=(16, 4.5), constrained_layout=True)
    for ax, (title, arr) in zip(axes, map_items):
        ax.imshow(arr, cmap=cmap, norm=norm, interpolation="nearest")
        ax.set_title(title, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
    maps_path = asset_dir / "twm_public_landcover_benchmark_maps.png"
    fig.savefig(maps_path, bbox_inches="tight", dpi=180)
    plt.close(fig)
    return {"metrics": rel_asset(metrics_path), "maps": rel_asset(maps_path)}


def rebuild_case_predictions(region: BenchmarkRegion, years: list[int]) -> dict[str, np.ndarray]:
    frames = {frame.year: frame for frame in region.frames}
    train_start = frames[years[0]]
    train_end = frames[years[1]]
    holdout = frames[years[2]]
    valid = valid_mask(train_start, train_end, holdout, region.classes)
    model_inputs = {
        "train_start": train_start.array,
        "train_end": train_end.array,
        "initial": train_end.array,
        "actual": holdout.array,
        "valid": valid,
        "classes": list(region.classes),
        "drivers": region.drivers,
        "train_years": max(1, train_end.year - train_start.year),
        "horizon_years": max(1, holdout.year - train_end.year),
        "region_id": region.region_id,
        "train_start_year": int(train_start.year),
        "train_end_year": int(train_end.year),
        "holdout_year": int(holdout.year),
    }
    forecast_counts = project_class_counts(
        train_start.array,
        train_end.array,
        valid,
        list(region.classes),
        train_years=model_inputs["train_years"],
        horizon_years=model_inputs["horizon_years"],
    )
    oracle_counts = class_counts(holdout.array, valid, list(region.classes))
    predictions, _ = build_candidates(model_inputs, forecast_counts, oracle_counts)
    return predictions


def rel_asset(path: Path) -> str:
    path = path.resolve()
    try:
        return str(path.relative_to(REPO_ROOT / "docs"))
    except ValueError:
        try:
            return str(path.relative_to(REPO_ROOT))
        except ValueError:
            return str(path)


def render_markdown_report(report: dict[str, Any]) -> str:
    assets = report.get("renderer", {}).get("assets") or {}
    lines = [
        "# TWM 公开多时期土地利用基准",
        "",
        "更新日期：2026-06-22",
        "",
        "## 1. 当前结论",
        "",
        "本轮新增的是 TWM 的公开数据基准入口：它面向 GLC_FCS30D、Dynamic World、MODIS 等本地导出的多时期土地覆盖栅格栈，也可以用现有 DongGuan 80m 样例作为真实数据适配验证。",
        "",
        "关键边界：`forecast_demand` 是正式预测设定；`oracle_demand` 使用目标年类别总量，只能作为上限诊断，不能作为真实预测结果。",
        "",
        "## 2. 数据画像",
        "",
        f"- source type: `{report['source'].get('source_type')}`",
        f"- region count: `{report['data_profile']['region_count']}`",
        f"- rolling case count: `{report['data_profile']['case_count']}`",
        "",
    ]
    if assets.get("maps"):
        lines.extend(["## 3. 渲染器输出", "", f"![Maps]({assets['maps']})", ""])
    if assets.get("metrics"):
        lines.extend([f"![Metrics]({assets['metrics']})", ""])
    lines.extend(
        [
            "## 4. 汇总指标",
            "",
            "| candidate | cases | mean OA | mean Kappa | mean change FoM | mean change F1 | mean macro F1 | target demand abs err | oracle demand abs err |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in report["summary"].get("ranking_by_mean_change_fom") or []:
        lines.append(
            f"| {item['candidate_id']} | {item['case_count']} | {item['mean_overall_accuracy']:.6f} | "
            f"{item['mean_kappa']:.6f} | {item['mean_change_fom']:.6f} | {item['mean_change_f1']:.6f} | "
            f"{item['mean_macro_f1']:.6f} | {item['total_target_demand_abs_error']} | {item['total_oracle_demand_abs_error']} |"
        )
    aggregate_components = report["summary"].get("aggregate_component_diagnostics") or {}
    aggregate_component_rows = aggregate_components.get("rows") or []
    if aggregate_component_rows:
        lines.extend(
            [
                "",
                "## 5. 组件贡献诊断",
                "",
                "下表为正式 `forecast_demand` 设定下，full TWM 相对各对照项的聚合差值。正值表示 full TWM 更好；`no_demand_projection` 只用于诊断，不能作为合法预测候选。",
                "",
                "| component | comparison | Δ full-comparison change FoM | Δ OA | Δ change F1 | Δ target demand error |",
                "|---|---|---:|---:|---:|---:|",
            ]
        )
        for row in aggregate_component_rows:
            lines.append(
                f"| {row['component']} | {row['comparison_candidate_id']} | "
                f"{row['change_fom_delta_full_minus_comparison']:.6f} | "
                f"{row['overall_accuracy_delta_full_minus_comparison']:.6f} | "
                f"{row['change_f1_delta_full_minus_comparison']:.6f} | "
                f"{row['target_demand_abs_error_delta_full_minus_comparison']} |"
            )
    training_rows = report["summary"].get("training_diagnostics_by_candidate") or {}
    if training_rows:
        lines.extend(
            [
                "",
                "## 6. 训练诊断",
                "",
                "| candidate | cases | pass | review | fitted source classes | pooled fallback | hard fallback | local/pooled rate | mean pooled weight | cross-region support | cross-region smoothed | mean smooth weight | solvers |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for candidate_id, diag in training_rows.items():
            solvers = ", ".join(f"{key}:{value}" for key, value in sorted((diag.get("solver_counts") or {}).items()))
            lines.append(
                f"| {candidate_id} | {diag['case_count']} | {diag['pass_case_count']} | {diag['review_case_count']} | "
                f"{diag['fitted_source_class_count']} | {diag.get('pooled_fallback_source_class_count', 0)} | "
                f"{diag.get('hard_fallback_source_class_count', diag['fallback_source_class_count'])} | "
                f"{diag.get('local_or_pooled_model_source_class_rate', 0.0):.6f} | "
                f"{diag.get('mean_pooled_fallback_weight', 0.0):.6f} | "
                f"{diag.get('cross_region_supported_source_class_rate', 0.0):.6f} | "
                f"{diag.get('cross_region_smoothed_source_class_rate', 0.0):.6f} | "
                f"{diag.get('mean_smoothing_weight', 0.0):.6f} | {solvers or 'n/a'} |"
            )
    lines.extend(["", "## 7. 单案例指标", ""])
    for experiment in report.get("experiments") or []:
        lines.extend(
            [
                f"### {experiment['case_id']}",
                "",
                f"- train: `{experiment['train_period']}`",
                f"- holdout: `{experiment['holdout_period']}`",
                f"- best forecast by change FoM: `{experiment['best_forecast_by_change_fom']}`",
                f"- best oracle by change FoM: `{experiment['best_oracle_by_change_fom']}`",
                f"- forecast demand abs error against oracle: `{experiment['demand']['forecast_total_abs_error_against_oracle']}`",
                "",
                "| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for name, metric in experiment["metrics"].items():
            mode = experiment["candidate_metadata"][name]["demand_mode"]
            lines.append(
                f"| {name} | {mode} | {metric['overall_accuracy']:.6f} | {metric['kappa']:.6f} | "
                f"{metric['change_fom']:.6f} | {metric['change_f1']:.6f} | {metric['macro_f1']:.6f} | "
                f"{metric['predicted_change_count']} |"
            )
        lines.append("")
        ablation_rows = (experiment.get("ablation_summary") or {}).get("rows") or []
        if ablation_rows:
            lines.extend(
                [
                    "Ablation deltas against `twm_independent_transition_forecast_demand`:",
                    "",
                    "| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |",
                    "|---|---:|---:|---:|---:|---:|",
                ]
            )
            for row in ablation_rows:
                lines.append(
                    f"| {row['candidate_id']} | {row['change_fom_delta_vs_full']:.6f} | "
                    f"{row['overall_accuracy_delta_vs_full']:.6f} | {row['change_f1_delta_vs_full']:.6f} | "
                    f"{row['target_demand_abs_error_delta_vs_full']} | {row['predicted_change_delta_vs_full']} |"
                )
            lines.append("")
    lines.extend(
        [
            "## 8. 下一步",
            "",
            "- 将当前 leave-region-out 跨区域平滑升级为真正的 region-holdout / temporal-holdout 参数共享实验，并报告分区域显著性。",
            "- 增加 road/accessibility、population、planning-policy、economic activity 等更接近土地变化机制的协变量，重新评估 no-driver ablation。",
            "- 将 demand 从简单历史趋势升级为独立情景需求模型，避免把模拟器能力和需求外推误差混在一起。",
            "- 缓存可复用特征栈和 per-source-class 拟合结果，降低 100-case 真实基准的迭代成本。",
            "",
        ]
    )
    return "\n".join(lines)


def neighbor_density(arr: np.ndarray, cls: int, valid: np.ndarray) -> np.ndarray:
    mask = ((arr == cls) & valid).astype(np.float32)
    padded = np.pad(mask, 1, mode="constant", constant_values=0.0)
    total = np.zeros(arr.shape, dtype=np.float32)
    for dr in (0, 1, 2):
        for dc in (0, 1, 2):
            if dr == 1 and dc == 1:
                continue
            total += padded[dr : dr + arr.shape[0], dc : dc + arr.shape[1]]
    return total / 8.0


def stable_cell_hash(shape: tuple[int, int], salt: int) -> np.ndarray:
    rows, cols = np.indices(shape)
    hashed = (rows * 73856093 + cols * 19349663 + salt * 83492791) % 1000003
    return (hashed.astype(np.float32) / 1000003.0).astype(np.float32)


def harmonic(precision: float, recall: float) -> float:
    if precision + recall <= 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


if __name__ == "__main__":
    main()
