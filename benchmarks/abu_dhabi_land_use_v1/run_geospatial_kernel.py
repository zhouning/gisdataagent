#!/usr/bin/env python3
"""Run the explicit GWM Geospatial Kernel on the unified Abu Dhabi bundle."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from scipy.ndimage import uniform_filter
from sklearn.ensemble import HistGradientBoostingClassifier

from data_agent.uwm.geospatial_kernel.runtime import (
    GEOSPATIAL_KERNEL_RUNTIME_SCHEMA,
    GeospatialKernelRuntime,
    KernelAction,
    KernelAdapterDescriptor,
    KernelConstraintProjection,
    KernelEvidenceRef,
    KernelProvenance,
    KernelState,
    KernelTransitionCandidate,
    build_kernel_capability_report,
    summarize_kernel_steps,
)

try:
    from .shared import CLASSES, class_counts, evaluate_prediction
except ImportError:  # Direct script execution from the benchmark directory.
    from shared import CLASSES, class_counts, evaluate_prediction

HERE = Path(__file__).resolve().parent
INPUT_ROOT = HERE / "artifacts/gee"
OSM_ROOT = HERE / "artifacts/osm"
BUNDLE_ROOT = HERE / "artifacts/bundle"
DEFAULT_OUTPUT = HERE / "artifacts/predictions/geospatial_kernel"
FIT_TRANSITIONS = ((2017, 2018), (2018, 2019), (2019, 2020), (2020, 2021))
SEEDS = (31, 47, 73)

ABU_DHABI_LU_GK_RUNTIME_ADAPTER = KernelAdapterDescriptor(
    adapter_id="abu-dhabi-lu-gk-runtime-adapter",
    adapter_version="1.0.0",
    domain="land_use_raster",
    state_semantics="100 metre categorical land-use raster within the frozen city mask",
    action_semantics="year-bound feasible class totals derived by the benchmark protocol",
    transition_semantics="learned cell transition probabilities with spatial neighborhood context",
    constraint_semantics="hard exclusion preservation and exact feasible class-total allocation",
)


def _read(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    with rasterio.open(path) as dataset:
        return dataset.read(), dataset.profile.copy()


def _write_state(
    path: Path,
    state: np.ndarray,
    reference: dict[str, Any],
    *,
    valid_mask: np.ndarray,
) -> None:
    profile = reference.copy()
    profile.update(
        count=1,
        dtype="uint8",
        nodata=0,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".partial.{os.getpid()}.tif")
    output = state.astype(np.uint8, copy=True)
    output[~valid_mask] = 0
    with rasterio.open(temp, "w", **profile) as dataset:
        dataset.write(output, 1)
        dataset.set_band_description(1, "predicted_land_cover")
    os.replace(temp, path)


def _neighborhood_features(state: np.ndarray, valid: np.ndarray) -> np.ndarray:
    layers = []
    denominator_3 = uniform_filter(valid.astype(np.float32), size=3, mode="constant")
    denominator_7 = uniform_filter(valid.astype(np.float32), size=7, mode="constant")
    for value in CLASSES:
        indicator = ((state == value) & valid).astype(np.float32)
        local_3 = uniform_filter(indicator, size=3, mode="constant")
        local_7 = uniform_filter(indicator, size=7, mode="constant")
        layers.append(
            np.divide(
                local_3,
                denominator_3,
                out=np.zeros_like(local_3),
                where=denominator_3 > 0,
            )
        )
        layers.append(
            np.divide(
                local_7,
                denominator_7,
                out=np.zeros_like(local_7),
                where=denominator_7 > 0,
            )
        )
    return np.stack(layers)


class AbuDhabiInputs:
    def __init__(self) -> None:
        city, self.reference = _read(HERE / "artifacts/abu_dhabi_city_100m_mask.tif")
        common, _ = _read(BUNDLE_ROOT / "common_valid_mask_100m.tif")
        self.city = city[0].astype(bool)
        self.valid = common[0].astype(bool)
        self.states = {
            year: _read(INPUT_ROOT / "land_cover" / f"land_cover_{year}_100m.tif")[0][0]
            for year in range(2017, 2025)
        }
        self.quality = {
            year: _read(INPUT_ROOT / "land_cover" / f"land_cover_quality_{year}_100m.tif")[0][0]
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
        self.hard = {
            year: _read(BUNDLE_ROOT / f"hard_exclusion_{year}_100m.tif")[0][0].astype(bool)
            for year in (2022, 2024)
        }
        rows, columns = np.indices(self.valid.shape)
        self.x = columns.astype(np.float32) / max(1, self.valid.shape[1] - 1)
        self.y = rows.astype(np.float32) / max(1, self.valid.shape[0] - 1)

    def features(self, state: np.ndarray, *, driver_year: int) -> np.ndarray:
        one_hot = np.stack([(state == value).astype(np.float32) for value in CLASSES])
        neighborhoods = _neighborhood_features(state, self.valid)
        continuous = np.stack(
            [
                self.x,
                self.y,
                np.clip(self.elevation, -20, 200) / 200.0,
                np.clip(self.slope, 0, 30) / 30.0,
                np.log1p(np.clip(self.viirs[driver_year], 0, None)) / 8.0,
                np.log1p(np.clip(self.road_distance, 0, None)) / 12.0,
                np.log1p(np.clip(self.major_road_distance, 0, None)) / 12.0,
            ]
        )
        return np.concatenate([one_hot, neighborhoods, continuous], axis=0)


def train_kernel(
    inputs: AbuDhabiInputs,
    *,
    seed: int,
) -> tuple[HistGradientBoostingClassifier, dict[str, Any]]:
    rng = np.random.default_rng(seed)
    feature_rows = []
    labels = []
    weights = []
    transition_rows = []
    for start_year, target_year in FIT_TRANSITIONS:
        start = inputs.states[start_year]
        target = inputs.states[target_year]
        features = inputs.features(start, driver_year=start_year)
        changed = inputs.valid & (start != target)
        selected = inputs.valid & (changed | (rng.random(start.shape) < 0.20))
        feature_rows.append(features[:, selected].T)
        labels.append(target[selected].astype(np.int64))
        confidence = np.minimum(
            inputs.quality[start_year][selected],
            inputs.quality[target_year][selected],
        )
        weights.append((1.0 + 5.0 * changed[selected]) * (0.5 + np.clip(confidence, 0, 1)))
        transition_rows.append(
            {
                "start_year": start_year,
                "target_year": target_year,
                "selected_pixels": int(selected.sum()),
                "selected_changed_pixels": int(changed[selected].sum()),
            }
        )
    x = np.concatenate(feature_rows)
    y = np.concatenate(labels)
    sample_weight = np.concatenate(weights)
    model = HistGradientBoostingClassifier(
        learning_rate=0.08,
        max_iter=120,
        max_leaf_nodes=31,
        min_samples_leaf=40,
        l2_regularization=1.0,
        random_state=seed,
    )
    started = time.perf_counter()
    model.fit(x, y, sample_weight=sample_weight)
    return model, {
        "seed": seed,
        "training_pixel_rows": len(x),
        "feature_count": x.shape[1],
        "model_classes": model.classes_.tolist(),
        "fit_transitions": transition_rows,
        "fit_seconds": time.perf_counter() - started,
    }


def probability_cube(
    model: HistGradientBoostingClassifier,
    inputs: AbuDhabiInputs,
    state: np.ndarray,
    *,
    driver_year: int,
) -> np.ndarray:
    features = inputs.features(state, driver_year=driver_year)
    probability = model.predict_proba(features[:, inputs.valid].T)
    cube = np.full((len(CLASSES), *state.shape), 1e-9, dtype=np.float32)
    for column, value in enumerate(model.classes_):
        cube[int(value) - 1][inputs.valid] = probability[:, column]
    cube /= cube.sum(axis=0, keepdims=True)
    return cube


def allocate_action(
    current: np.ndarray,
    probability: np.ndarray,
    *,
    valid: np.ndarray,
    hard: np.ndarray,
    target_counts: dict[int, int],
    neighborhood_weight: float = 0.35,
) -> tuple[np.ndarray, dict[str, Any]]:
    result = current.copy()
    current_counts = class_counts(result, valid)
    excess = {value: max(0, current_counts[value] - target_counts[value]) for value in CLASSES}
    deficit = {value: max(0, target_counts[value] - current_counts[value]) for value in CLASSES}
    neighborhoods = _neighborhood_features(result, valid)[1::2]
    candidate_scores = []
    candidate_pixels = []
    candidate_targets = []
    candidate_sources = []
    flat_result = result.ravel()
    mutable_flat = (valid & ~hard).ravel()
    for target in CLASSES:
        if deficit[target] <= 0:
            continue
        for source in CLASSES:
            if source == target or excess[source] <= 0:
                continue
            candidates = np.flatnonzero(mutable_flat & (flat_result == source))
            if not len(candidates):
                continue
            score = (
                np.log(np.clip(probability[target - 1].ravel()[candidates], 1e-9, 1))
                - np.log(np.clip(probability[source - 1].ravel()[candidates], 1e-9, 1))
                + neighborhood_weight * neighborhoods[target - 1].ravel()[candidates]
            )
            candidate_scores.append(score)
            candidate_pixels.append(candidates)
            candidate_targets.append(np.full(len(candidates), target, dtype=np.int16))
            candidate_sources.append(np.full(len(candidates), source, dtype=np.int16))
    if candidate_scores:
        scores = np.concatenate(candidate_scores)
        pixels = np.concatenate(candidate_pixels)
        targets = np.concatenate(candidate_targets)
        sources = np.concatenate(candidate_sources)
        order = np.argsort(-scores, kind="stable")
        moved = 0
        for index in order:
            pixel = int(pixels[index])
            source = int(sources[index])
            target = int(targets[index])
            if flat_result[pixel] != source or excess[source] <= 0 or deficit[target] <= 0:
                continue
            flat_result[pixel] = target
            excess[source] -= 1
            deficit[target] -= 1
            moved += 1
            if not any(deficit.values()):
                break
    else:
        moved = 0
    if any(deficit.values()) or any(excess.values()):
        raise RuntimeError(f"geospatial_kernel_allocation_infeasible:{excess}:{deficit}")
    if np.any(result[hard & valid] != current[hard & valid]):
        raise AssertionError("geospatial_kernel_changed_hard_exclusion")
    return result, {"moved_pixels": moved, "target_counts": target_counts}


@dataclass(frozen=True)
class AbuDhabiLUKernelContext:
    model: HistGradientBoostingClassifier
    inputs: AbuDhabiInputs
    driver_year: int
    hard_exclusion: np.ndarray
    parameter_ref: str


class AbuDhabiLUKernelAdapter:
    """Bind the Abu Dhabi LU transition and allocation to the common runtime."""

    descriptor = ABU_DHABI_LU_GK_RUNTIME_ADAPTER

    def propose_transition(
        self,
        *,
        state: KernelState[np.ndarray],
        action: KernelAction[dict[str, Any]],
        context: AbuDhabiLUKernelContext,
    ) -> KernelTransitionCandidate[np.ndarray]:
        probability = probability_cube(
            context.model,
            context.inputs,
            state.payload,
            driver_year=context.driver_year,
        )
        return KernelTransitionCandidate(
            payload=probability,
            diagnostics={
                "candidate_kind": "land_use_class_probability_cube",
                "class_count": len(CLASSES),
                "valid_pixel_count": int(context.inputs.valid.sum()),
                "driver_year": context.driver_year,
            },
        )

    def project_constraints(
        self,
        *,
        state: KernelState[np.ndarray],
        action: KernelAction[dict[str, Any]],
        candidate: KernelTransitionCandidate[np.ndarray],
        context: AbuDhabiLUKernelContext,
    ) -> KernelConstraintProjection[np.ndarray]:
        target_counts = _target_counts(action.payload)
        next_state, allocation = allocate_action(
            state.payload,
            candidate.payload,
            valid=context.inputs.valid,
            hard=context.hard_exclusion,
            target_counts=target_counts,
        )
        return KernelConstraintProjection(
            state_payload=next_state,
            status="projected",
            state_ref=f"abu-dhabi-lu-gk:{action.action_id}:{action.target_time}",
            provenance=KernelProvenance(
                model_id="HistGradientBoostingClassifier+LU-GK-allocation",
                model_version=self.descriptor.adapter_version,
                parameter_ref=context.parameter_ref,
                evidence=state.evidence + action.evidence,
                metadata={
                    "benchmark_id": "abu-dhabi-land-use-v1",
                    "oracle_allocation_action": True,
                    "reliability_mask_read_by_model": False,
                },
            ),
            diagnostics={
                **allocation,
                "hard_exclusion_changed_pixels": int(
                    np.count_nonzero(
                        context.inputs.valid
                        & context.hard_exclusion
                        & (next_state != state.payload)
                    )
                ),
            },
        )


def _load_actions() -> list[dict[str, Any]]:
    return json.loads((BUNDLE_ROOT / "allocation_actions.json").read_text())["actions"]


def _target_counts(action: dict[str, Any]) -> dict[int, int]:
    return {int(key): int(value) for key, value in action["feasible_target_counts"].items()}


def run_seed(
    inputs: AbuDhabiInputs,
    *,
    seed: int,
    output_root: Path,
) -> dict[str, Any]:
    model, training = train_kernel(inputs, seed=seed)
    current = inputs.states[2022].copy()
    runtime = GeospatialKernelRuntime(AbuDhabiLUKernelAdapter())
    state = KernelState(
        domain=ABU_DHABI_LU_GK_RUNTIME_ADAPTER.domain,
        time_id="2022",
        state_ref="artifacts/gee/land_cover/land_cover_2022_100m.tif",
        payload=current,
        evidence=(
            KernelEvidenceRef(
                uri="artifacts/gee/land_cover/land_cover_2022_100m.tif",
                role="initial_state",
            ),
        ),
    )
    year_reports = []
    step_results = []
    actions = _load_actions()
    for action_payload in actions:
        target_year = int(action_payload["target_year"])
        action = KernelAction(
            action_id=str(action_payload["action_id"]),
            domain=ABU_DHABI_LU_GK_RUNTIME_ADAPTER.domain,
            source_time=str(action_payload["start_year"]),
            target_time=str(target_year),
            payload=action_payload,
            evidence=(
                KernelEvidenceRef(
                    uri="artifacts/bundle/allocation_actions.json",
                    role="bounded_allocation_action",
                ),
            ),
        )
        step = runtime.step(
            state=state,
            action=action,
            context=AbuDhabiLUKernelContext(
                model=model,
                inputs=inputs,
                driver_year=2022,
                hard_exclusion=inputs.hard[2022],
                parameter_ref=f"in-memory-fit:seed-{seed}",
            ),
        )
        step_results.append(step)
        state = step.next_state
        current = state.payload
        allocation = dict(step.projection.diagnostics)
        path = output_root / f"seed_{seed}" / f"prediction_{target_year}.tif"
        _write_state(path, current, inputs.reference, valid_mask=inputs.valid)
        reliability, _ = _read(HERE / action_payload["reliability_mask"])
        evaluation = evaluate_prediction(
            current,
            origin_state=inputs.states[2022],
            observed_target=inputs.states[target_year],
            valid_mask=inputs.valid,
            hard_exclusion_mask=inputs.hard[2022],
            requested_counts=_target_counts(action_payload),
            reliability_mask=reliability[0].astype(bool),
        )
        year_reports.append(
            {
                "target_year": target_year,
                "prediction_path": str(path.relative_to(HERE)),
                "allocation": allocation,
                "evaluation": evaluation,
                "kernel_step": step.audit(),
            }
        )
    return {
        "seed": seed,
        "training": training,
        "kernel_runtime_execution_summary": summarize_kernel_steps(
            adapter=ABU_DHABI_LU_GK_RUNTIME_ADAPTER,
            expected_step_count=len(actions),
            steps=step_results,
        ),
        "years": year_reports,
    }


def run(*, seeds: tuple[int, ...], output_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    inputs = AbuDhabiInputs()
    seed_reports = []
    for seed in seeds:
        seed_reports.append(run_seed(inputs, seed=seed, output_root=output_root))
        print(f"geospatial_kernel:seed_{seed}:complete", flush=True)
    report = {
        "schema": "gwm.abu_dhabi_geospatial_kernel_run.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "model_id": "gwm_geospatial_kernel",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "state_writeback": True,
        "test_label_access_during_fit": False,
        "kernel_runtime_schema": GEOSPATIAL_KERNEL_RUNTIME_SCHEMA,
        "kernel_capabilities": build_kernel_capability_report([ABU_DHABI_LU_GK_RUNTIME_ADAPTER]),
        "seeds": seed_reports,
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
    parser.add_argument("--seeds", default=",".join(str(value) for value in SEEDS))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    seeds = tuple(int(value) for value in args.seeds.split(",") if value.strip())
    report = run(seeds=seeds, output_root=args.output)
    print(
        json.dumps(
            {
                "status": report["status"],
                "seeds": [row["seed"] for row in report["seeds"]],
                "wall_seconds": report["wall_seconds"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
