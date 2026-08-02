#!/usr/bin/env python3
"""Run all three real model implementations on frozen 2025-2030 scenarios."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import rasterio
import torch

from data_agent.uwm.geospatial_kernel import (
    GEOSPATIAL_KERNEL_RUNTIME_SCHEMA,
    GeospatialKernelRuntime,
    KernelAction,
    KernelEvidenceRef,
    KernelState,
    build_kernel_capability_report,
    summarize_kernel_steps,
)

try:
    from .run_geosos_flus import (
        DEFAULT_BINARY,
        FlusInputs,
        simulate_year,
        train_suitability,
    )
    from .run_geospatial_kernel import (
        ABU_DHABI_LU_GK_RUNTIME_ADAPTER,
        AbuDhabiInputs,
        AbuDhabiLUKernelAdapter,
        AbuDhabiLUKernelContext,
        allocate_action,
        train_kernel,
    )
    from .shared import class_counts
except ImportError:  # Direct script execution from the benchmark directory.
    from run_geosos_flus import (
        DEFAULT_BINARY,
        FlusInputs,
        simulate_year,
        train_suitability,
    )
    from run_geospatial_kernel import (
        ABU_DHABI_LU_GK_RUNTIME_ADAPTER,
        AbuDhabiInputs,
        AbuDhabiLUKernelAdapter,
        AbuDhabiLUKernelContext,
        allocate_action,
        train_kernel,
    )
    from shared import class_counts

HERE = Path(__file__).resolve().parent
PAPER58_ROOT = HERE.parents[2] / "paper58-geofm-world-model-rl"
PAPER58_RUNNER_PATH = PAPER58_ROOT / "experiments/abu_dhabi/run_paper58_abu_dhabi.py"
BUNDLE_ROOT = HERE / "artifacts/bundle"
DEFAULT_OUTPUT = HERE / "artifacts/planning"
DEFAULT_REPORT = HERE / "planning_scenario_report.json"
SEEDS = (31, 47, 73)
MODEL_IDS = ("geosos_flus", "geospatial_kernel", "paper58")


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
    temporary = path.with_suffix(f".partial.{os.getpid()}.tif")
    output = state.astype(np.uint8, copy=True)
    output[~valid_mask] = 0
    with rasterio.open(temporary, "w", **profile) as dataset:
        dataset.write(output, 1)
        dataset.set_band_description(1, "scenario_land_cover")
    os.replace(temporary, path)


def _load_scenarios() -> list[dict[str, Any]]:
    return json.loads((BUNDLE_ROOT / "planning_scenarios.json").read_text(encoding="utf-8"))[
        "scenarios"
    ]


def _target_counts(scenario: dict[str, Any], year: int) -> dict[int, int]:
    return {
        int(key): int(value) for key, value in scenario["target_counts_by_year"][str(year)].items()
    }


def _action_record(scenario: dict[str, Any], year: int) -> dict[str, Any]:
    return {
        "schema": "gwm.land_use_planning_action.v1",
        "action_id": f"{scenario['scenario_id']}_{year - 1}_{year}",
        "scenario_id": str(scenario["scenario_id"]),
        "start_year": year - 1,
        "target_year": year,
        "feasible_target_counts": {
            str(key): value for key, value in _target_counts(scenario, year).items()
        },
    }


def _prediction_path(
    output_root: Path,
    *,
    model_id: str,
    scenario_id: str,
    seed: int,
    year: int,
) -> Path:
    return output_root / model_id / scenario_id / f"seed_{seed}" / f"prediction_{year}.tif"


def _report_path(path: Path) -> str:
    try:
        return str(path.relative_to(HERE))
    except ValueError:
        return str(path.resolve())


def run_geospatial_kernel_scenarios(*, seeds: tuple[int, ...], output_root: Path) -> dict[str, Any]:
    inputs = AbuDhabiInputs()
    scenarios = _load_scenarios()
    rows = []
    started = time.perf_counter()
    for seed in seeds:
        model, training = train_kernel(inputs, seed=seed)
        scenario_rows = []
        for scenario in scenarios:
            scenario_id = str(scenario["scenario_id"])
            current = inputs.states[2024].copy()
            runtime = GeospatialKernelRuntime(AbuDhabiLUKernelAdapter())
            state = KernelState(
                domain=ABU_DHABI_LU_GK_RUNTIME_ADAPTER.domain,
                time_id="2024",
                state_ref="artifacts/gee/land_cover/land_cover_2024_100m.tif",
                payload=current,
                evidence=(
                    KernelEvidenceRef(
                        uri="artifacts/gee/land_cover/land_cover_2024_100m.tif",
                        role="planning_initial_state",
                    ),
                ),
            )
            year_rows = []
            step_results = []
            for year in range(2025, 2031):
                target_counts = _target_counts(scenario, year)
                action_payload = _action_record(scenario, year)
                action = KernelAction(
                    action_id=str(action_payload["action_id"]),
                    domain=ABU_DHABI_LU_GK_RUNTIME_ADAPTER.domain,
                    source_time=str(action_payload["start_year"]),
                    target_time=str(action_payload["target_year"]),
                    payload=action_payload,
                    evidence=(
                        KernelEvidenceRef(
                            uri="artifacts/bundle/planning_scenarios.json",
                            role="planner_supplied_bounded_action",
                        ),
                    ),
                )
                step = runtime.step(
                    state=state,
                    action=action,
                    context=AbuDhabiLUKernelContext(
                        model=model,
                        inputs=inputs,
                        driver_year=2024,
                        hard_exclusion=inputs.hard[2024],
                        parameter_ref=f"in-memory-fit:seed-{seed}",
                    ),
                )
                step_results.append(step)
                state = step.next_state
                current = state.payload
                allocation = dict(step.projection.diagnostics)
                path = _prediction_path(
                    output_root,
                    model_id="geospatial_kernel",
                    scenario_id=scenario_id,
                    seed=seed,
                    year=year,
                )
                _write_state(path, current, inputs.reference, valid_mask=inputs.valid)
                year_rows.append(
                    {
                        "target_year": year,
                        "target_counts": target_counts,
                        "prediction_path": _report_path(path),
                        "allocation": allocation,
                        "kernel_step": step.audit(),
                    }
                )
            scenario_rows.append(
                {
                    "scenario_id": scenario_id,
                    "kernel_runtime_execution_summary": summarize_kernel_steps(
                        adapter=ABU_DHABI_LU_GK_RUNTIME_ADAPTER,
                        expected_step_count=6,
                        steps=step_results,
                    ),
                    "years": year_rows,
                }
            )
        rows.append({"seed": seed, "training": training, "scenarios": scenario_rows})
        print(f"planning:geospatial_kernel:seed_{seed}:complete", flush=True)
    return {
        "model_id": "geospatial_kernel",
        "implementation": "learned_explicit_geospatial_kernel",
        "future_exogenous_driver_policy": "hold_2024",
        "kernel_runtime_schema": GEOSPATIAL_KERNEL_RUNTIME_SCHEMA,
        "kernel_capabilities": build_kernel_capability_report([ABU_DHABI_LU_GK_RUNTIME_ADAPTER]),
        "seeds": rows,
        "wall_seconds": time.perf_counter() - started,
    }


def run_geosos_flus_scenarios(
    *, binary: Path, seeds: tuple[int, ...], output_root: Path
) -> dict[str, Any]:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise FileNotFoundError(f"flus_binary_not_executable:{binary}")
    inputs = FlusInputs()
    hard, _ = _read(BUNDLE_ROOT / "hard_exclusion_2024_100m.tif")
    inputs.hard = hard[0].astype(bool)
    scenarios = _load_scenarios()
    rows = []
    started = time.perf_counter()
    for seed in seeds:
        probability, training = train_suitability(
            inputs,
            binary=binary.resolve(),
            seed=seed,
            work_root=output_root / "geosos_flus/work" / f"seed_{seed}/ann",
            target_driver_year=2024,
        )
        scenario_rows = []
        for scenario in scenarios:
            scenario_id = str(scenario["scenario_id"])
            current = inputs.states[2024].copy()
            year_rows = []
            for year in range(2025, 2031):
                current, simulation = simulate_year(
                    current,
                    probability,
                    action=_action_record(scenario, year),
                    inputs=inputs,
                    binary=binary.resolve(),
                    seed=seed,
                    work_root=(
                        output_root / "geosos_flus/work" / f"seed_{seed}" / scenario_id / str(year)
                    ),
                )
                path = _prediction_path(
                    output_root,
                    model_id="geosos_flus",
                    scenario_id=scenario_id,
                    seed=seed,
                    year=year,
                )
                _write_state(path, current, inputs.reference, valid_mask=inputs.valid)
                year_rows.append(
                    {
                        "target_year": year,
                        "target_counts": simulation["target_counts"],
                        "prediction_path": _report_path(path),
                        "simulation": simulation,
                    }
                )
            scenario_rows.append({"scenario_id": scenario_id, "years": year_rows})
        rows.append({"seed": seed, "training": training, "scenarios": scenario_rows})
        print(f"planning:geosos_flus:seed_{seed}:complete", flush=True)
    return {
        "model_id": "geosos_flus",
        "implementation": "external_flus_console_ann_ca",
        "external_binary": str(binary.resolve()),
        "future_exogenous_driver_policy": "hold_2024",
        "seeds": rows,
        "wall_seconds": time.perf_counter() - started,
    }


def _load_paper58_runner() -> ModuleType:
    if str(PAPER58_ROOT) not in sys.path:
        sys.path.insert(0, str(PAPER58_ROOT))
    spec = importlib.util.spec_from_file_location("paper58_abu_dhabi_runner", PAPER58_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"paper58_runner_not_loadable:{PAPER58_RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _paper58_probability(decoder: Any, embedding: np.ndarray) -> np.ndarray:
    logits = decoder.coef_ @ embedding.reshape(64, -1) + decoder.intercept_[:, None]
    logits -= logits.max(axis=0, keepdims=True)
    probability = np.exp(logits)
    probability /= probability.sum(axis=0, keepdims=True)
    return probability.reshape(6, *embedding.shape[1:]).astype(np.float32)


def run_paper58_scenarios(
    *, seeds: tuple[int, ...], output_root: Path, requested_device: str
) -> dict[str, Any]:
    runner = _load_paper58_runner()
    device = runner.choose_device(requested_device)
    data = runner.BenchmarkData(HERE)
    hard, _ = _read(BUNDLE_ROOT / "hard_exclusion_2024_100m.tif")
    hard_mask = hard[0].astype(bool)
    scenarios = _load_scenarios()
    rows = []
    started = time.perf_counter()
    for seed in seeds:
        decoder, decoder_report = runner.train_decoder(data, seed=seed)
        model = runner.build_demand_conditioned_model(6, z_dim=64, n_context=0).to(device)
        checkpoint = HERE / f"artifacts/predictions/paper58/seed_{seed}/paper58_ldn.pt"
        if not checkpoint.is_file():
            raise FileNotFoundError(f"paper58_checkpoint_missing:{checkpoint}")
        model.load_state_dict(torch.load(checkpoint, map_location=device, weights_only=True))
        model.eval()
        scenario_rows = []
        for scenario in scenarios:
            scenario_id = str(scenario["scenario_id"])
            current_embedding = data.embedding(2024).copy()
            current_state = data.states[2024].copy()
            year_rows = []
            for year in range(2025, 2031):
                record = _action_record(scenario, year)
                target_counts = _target_counts(scenario, year)
                action = runner.action_from_record(record, class_counts(current_state, data.valid))
                predicted_embedding = runner.predict_tiled(
                    model,
                    current_embedding,
                    action,
                    device=device,
                )
                predicted_embedding[:, hard_mask & data.valid] = current_embedding[
                    :, hard_mask & data.valid
                ]
                probability = _paper58_probability(decoder, predicted_embedding)
                current_state, allocation = allocate_action(
                    current_state,
                    probability,
                    valid=data.valid,
                    hard=hard_mask,
                    target_counts=target_counts,
                )
                current_embedding = predicted_embedding
                path = _prediction_path(
                    output_root,
                    model_id="paper58",
                    scenario_id=scenario_id,
                    seed=seed,
                    year=year,
                )
                _write_state(path, current_state, data.reference, valid_mask=data.valid)
                year_rows.append(
                    {
                        "target_year": year,
                        "target_counts": target_counts,
                        "prediction_path": _report_path(path),
                        "allocation": allocation,
                    }
                )
            scenario_rows.append({"scenario_id": scenario_id, "years": year_rows})
        rows.append({"seed": seed, "decoder": decoder_report, "scenarios": scenario_rows})
        print(f"planning:paper58:seed_{seed}:complete", flush=True)
    return {
        "model_id": "paper58",
        "implementation": "demand_conditioned_ldn_checkpoint",
        "device": str(device),
        "future_exogenous_driver_policy": "recursive_latent_writeback",
        "seeds": rows,
        "wall_seconds": time.perf_counter() - started,
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run(
    *,
    model_ids: tuple[str, ...],
    seeds: tuple[int, ...],
    output_root: Path,
    report_path: Path,
    binary: Path,
    requested_device: str,
) -> dict[str, Any]:
    unknown = sorted(set(model_ids) - set(MODEL_IDS))
    if unknown:
        raise ValueError(f"unknown_models:{unknown}")
    preserved_models = {}
    if report_path.is_file():
        existing = json.loads(report_path.read_text(encoding="utf-8"))
        if existing.get("schema") == "gwm.abu_dhabi_planning_scenarios.v1" and existing.get(
            "seeds"
        ) == list(seeds):
            preserved_models = {
                key: value
                for key, value in existing.get("models", {}).items()
                if key not in model_ids
            }
    report = {
        "schema": "gwm.abu_dhabi_planning_scenarios.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "origin_year": 2024,
        "target_years": list(range(2025, 2031)),
        "scenario_ids": [row["scenario_id"] for row in _load_scenarios()],
        "seeds": list(seeds),
        "common_action_and_constraint_contract": True,
        "models": preserved_models,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_report(report_path, report)
    for model_id in model_ids:
        if model_id == "geospatial_kernel":
            model_report = run_geospatial_kernel_scenarios(seeds=seeds, output_root=output_root)
        elif model_id == "geosos_flus":
            model_report = run_geosos_flus_scenarios(
                binary=binary, seeds=seeds, output_root=output_root
            )
        else:
            model_report = run_paper58_scenarios(
                seeds=seeds,
                output_root=output_root,
                requested_device=requested_device,
            )
        report["models"][model_id] = model_report
        _write_report(report_path, report)
    report["status"] = "complete"
    report["completed_at"] = datetime.now(UTC).isoformat()
    _write_report(report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default=",".join(MODEL_IDS))
    parser.add_argument("--seeds", default=",".join(str(value) for value in SEEDS))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    report = run(
        model_ids=tuple(value for value in args.models.split(",") if value),
        seeds=tuple(int(value) for value in args.seeds.split(",") if value),
        output_root=args.output,
        report_path=args.report,
        binary=args.binary,
        requested_device=args.device,
    )
    print(json.dumps({"status": report["status"], "models": list(report["models"])}))


if __name__ == "__main__":
    main()
