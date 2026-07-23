#!/usr/bin/env python3
"""Run and seal the three deterministic V3 internal baselines."""

from __future__ import annotations

import argparse
import time
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


CLASS_COUNT = 9
TARGET_YEARS = (2023, 2024, 2025)
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021, 2022)
DEVELOPMENT_ROOT = REPO_ROOT / "data/twm_public_landcover/gee_dynamic_world"
DEVELOPMENT_MANIFEST_PATH = DEVELOPMENT_ROOT / "twm_dynamic_world_manifest.json"
DEFAULT_OUTPUT_ROOT = DRAFT_ROOT / "predictions"
ADJACENCY_BLEND = 0.5
LAPLACE_ALPHA = 1.0


def _development_raster_rows() -> list[dict[str, Any]]:
    manifest = load_json(DEVELOPMENT_MANIFEST_PATH)
    if len(manifest["regions"]) != 20:
        raise ValueError("development_manifest_must_contain_exactly_20_regions")
    rows: list[dict[str, Any]] = []
    for region in manifest["regions"]:
        by_year = {
            int(row["year"]): row for row in region["raster_stack"]
        }
        if any(year not in by_year for year in DEVELOPMENT_YEARS):
            raise ValueError(
                f"development_region_missing_2017_2022:{region['region_id']}"
            )
        for year in DEVELOPMENT_YEARS:
            path = DEVELOPMENT_ROOT / by_year[year]["path"]
            if not path.is_file():
                raise FileNotFoundError(path)
            rows.append(
                {
                    "region_id": region["region_id"],
                    "year": year,
                    "path": str(path.relative_to(REPO_ROOT)),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return sorted(rows, key=lambda row: (row["region_id"], row["year"]))


def _transition_model(
    source_rows: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    by_region: dict[str, dict[int, Path]] = {}
    for row in source_rows:
        by_region.setdefault(row["region_id"], {})[int(row["year"])] = (
            REPO_ROOT / row["path"]
        )
    counts = np.full(
        (CLASS_COUNT, CLASS_COUNT), LAPLACE_ALPHA, dtype=np.float64
    )
    raw_transition_count = 0
    valid_pixel_year_pairs = 0
    for region_id in sorted(by_region):
        arrays: dict[int, np.ndarray] = {}
        reference_shape: tuple[int, int] | None = None
        reference_transform = None
        reference_crs = None
        for year in DEVELOPMENT_YEARS:
            path = by_region[region_id][year]
            with rasterio.open(path) as dataset:
                array = dataset.read(1)
                if reference_shape is None:
                    reference_shape = array.shape
                    reference_transform = dataset.transform
                    reference_crs = dataset.crs
                elif (
                    array.shape != reference_shape
                    or dataset.transform != reference_transform
                    or dataset.crs != reference_crs
                ):
                    raise ValueError(
                        f"development_grid_mismatch:{region_id}:{year}"
                    )
                arrays[year] = array
        for source_year, target_year in zip(
            DEVELOPMENT_YEARS[:-1], DEVELOPMENT_YEARS[1:]
        ):
            source = arrays[source_year].astype(np.int64, copy=False)
            target = arrays[target_year].astype(np.int64, copy=False)
            valid = (
                (source >= 0)
                & (source < CLASS_COUNT)
                & (target >= 0)
                & (target < CLASS_COUNT)
            )
            source_valid = source[valid]
            target_valid = target[valid]
            flat_index = source_valid * CLASS_COUNT + target_valid
            pair_counts = np.bincount(
                flat_index, minlength=CLASS_COUNT * CLASS_COUNT
            ).reshape(CLASS_COUNT, CLASS_COUNT)
            counts += pair_counts
            pair_count = int(valid.sum())
            raw_transition_count += pair_count
            valid_pixel_year_pairs += 1
    transition = counts / counts.sum(axis=1, keepdims=True)
    details = {
        "development_region_count": len(by_region),
        "development_years_read": list(DEVELOPMENT_YEARS),
        "maximum_development_label_year_read": max(DEVELOPMENT_YEARS),
        "source_raster_count": len(source_rows),
        "valid_region_year_transition_pairs": valid_pixel_year_pairs,
        "raw_valid_pixel_transition_count": raw_transition_count,
        "laplace_alpha_per_cell": LAPLACE_ALPHA,
    }
    return counts, transition, details


def _submission_frame(
    expected_keys: pd.DataFrame,
    probability_by_key: dict[tuple[str, str, int], np.ndarray],
) -> pd.DataFrame:
    probability = np.stack(
        [
            probability_by_key[(row.region_id, row.node_id, int(row.target_year))]
            for row in expected_keys.itertuples(index=False)
        ]
    )
    frame = expected_keys.copy()
    frame[PROBABILITY_COLUMNS] = probability
    return frame[KEY_COLUMNS + PROBABILITY_COLUMNS]


def _persistence(
    inputs: pd.DataFrame, expected_keys: pd.DataFrame
) -> pd.DataFrame:
    by_node = inputs.set_index(["region_id", "node_id"])["land_class_2022"]
    probability_by_key = {}
    identity = np.eye(CLASS_COUNT, dtype=np.float64)
    for row in expected_keys.itertuples(index=False):
        probability_by_key[(row.region_id, row.node_id, int(row.target_year))] = (
            identity[int(by_node.loc[(row.region_id, row.node_id)])]
        )
    return _submission_frame(expected_keys, probability_by_key)


def _nonspatial_history(
    inputs: pd.DataFrame,
    expected_keys: pd.DataFrame,
    transition: np.ndarray,
) -> pd.DataFrame:
    probability_by_key = {}
    identity = np.eye(CLASS_COUNT, dtype=np.float64)
    for row in inputs.sort_values(["region_id", "node_id"]).itertuples(index=False):
        state = identity[int(row.land_class_2022)].copy()
        for target_year in TARGET_YEARS:
            state = state @ transition
            probability_by_key[(row.region_id, row.node_id, target_year)] = (
                state.copy()
            )
    return _submission_frame(expected_keys, probability_by_key)


def _fixed_adjacency(
    inputs: pd.DataFrame,
    edges: pd.DataFrame,
    expected_keys: pd.DataFrame,
    transition: np.ndarray,
) -> pd.DataFrame:
    probability_by_key = {}
    identity = np.eye(CLASS_COUNT, dtype=np.float64)
    for region_id, region in inputs.groupby("region_id", sort=True):
        region = region.sort_values("node_id", kind="mergesort").reset_index(
            drop=True
        )
        node_ids = region["node_id"].tolist()
        node_index = {node_id: index for index, node_id in enumerate(node_ids)}
        neighbors: list[list[int]] = [[] for _ in node_ids]
        for edge in edges[edges["region_id"] == region_id].itertuples(index=False):
            source = node_index.get(edge.source_node_id)
            target = node_index.get(edge.target_node_id)
            if source is not None and target is not None:
                neighbors[source].append(target)
        state = identity[
            region["land_class_2022"].to_numpy(dtype=np.int64)
        ].copy()
        for target_year in TARGET_YEARS:
            neighbor_state = np.stack(
                [
                    state[indexes].mean(axis=0) if indexes else state[index]
                    for index, indexes in enumerate(neighbors)
                ]
            )
            state = (
                (1.0 - ADJACENCY_BLEND) * (state @ transition)
                + ADJACENCY_BLEND * (neighbor_state @ transition)
            )
            state /= state.sum(axis=1, keepdims=True)
            for index, node_id in enumerate(node_ids):
                probability_by_key[(region_id, node_id, target_year)] = state[
                    index
                ].copy()
    return _submission_frame(expected_keys, probability_by_key)


def _model_spec(
    *,
    model_id: str,
    source_fingerprint: str,
    counts: np.ndarray,
    transition: np.ndarray,
    training_details: dict[str, Any],
) -> dict[str, Any]:
    common = {
        "schema": "gwm_bench.v3_internal_baseline_model.v1",
        "model_id": model_id,
        "forecast_origin_year": 2022,
        "target_years": list(TARGET_YEARS),
        "rollout": "three_step_open_loop_without_observed_writeback",
        "class_count": CLASS_COUNT,
        "target_labels_used": False,
        "post_2022_lockbox_pixels_read": False,
    }
    if model_id == "state_persistence":
        return {
            **common,
            "algorithm": "repeat the 2022 class as a one-hot distribution",
            "learned_parameters": False,
            "development_source_fingerprint": None,
        }
    spec = {
        **common,
        "algorithm": "global first-order Markov transition estimated from all valid full-grid development pixels",
        "development_source_fingerprint": source_fingerprint,
        "training": training_details,
        "transition_counts_with_smoothing": counts.tolist(),
        "transition_probability": transition.tolist(),
    }
    if model_id == "fixed_adjacency_spatial":
        spec.update(
            {
                "spatial_graph": "frozen directed four-neighbor Phase A graph",
                "update": "equal blend of own and neighbor previous predicted distributions, then the same global transition",
                "adjacency_blend": ADJACENCY_BLEND,
                "adjacency_blend_origin": "pre-existing V1 fixed-adjacency baseline; not selected on V3 lockbox labels",
            }
        )
    return spec


def run(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    started = time.perf_counter()
    protocol = load_json(PROTOCOL_PATH)
    firewall_before = enforce_label_firewall(protocol)
    bundle_manifest = load_json(BUNDLE_MANIFEST_PATH)
    contract, expected_keys = load_prediction_contract()
    inputs = pd.read_parquet(BUNDLE_ROOT / "observed_inputs.parquet")
    edges = pd.read_parquet(BUNDLE_ROOT / "observed_edges.parquet")

    output_root.mkdir(parents=True, exist_ok=True)
    environment_path = output_root / "runtime_environment.json"
    write_json_atomic(runtime_environment(), environment_path)

    source_rows = _development_raster_rows()
    source_payload = {
        "schema": "gwm_bench.v3_development_transition_sources.v1",
        "purpose": "label-safe global transition estimation for V3 internal baselines",
        "allowed_years": list(DEVELOPMENT_YEARS),
        "post_2022_pixel_values_read": False,
        "artifacts": source_rows,
    }
    source_payload["source_fingerprint"] = fingerprint(source_payload)
    source_path = output_root / "development_transition_source_manifest.json"
    write_json_atomic(source_payload, source_path)

    counts, transition, training_details = _transition_model(source_rows)
    frames = {
        "state_persistence": _persistence(inputs, expected_keys),
        "nonspatial_history_only": _nonspatial_history(
            inputs, expected_keys, transition
        ),
        "fixed_adjacency_spatial": _fixed_adjacency(
            inputs, edges, expected_keys, transition
        ),
    }

    reports: dict[str, Any] = {}
    source_artifact = artifact(
        Path(__file__), role="runtime_r2_internal_baseline_adapter_source"
    )
    runtime_artifact = artifact(
        environment_path, role="runtime_environment_descriptor"
    )
    development_artifact = artifact(
        source_path, role="development_transition_source_manifest"
    )
    for model_id, raw_frame in frames.items():
        model_started = time.perf_counter()
        frame = validate_submission(
            raw_frame, contract=contract, expected_keys=expected_keys
        )
        model_root = output_root / model_id
        model_root.mkdir(parents=True, exist_ok=True)
        spec = _model_spec(
            model_id=model_id,
            source_fingerprint=source_payload["source_fingerprint"],
            counts=counts,
            transition=transition,
            training_details=training_details,
        )
        spec_path = model_root / "model_spec.json"
        write_json_atomic(spec, spec_path)
        prediction_path = model_root / "prediction.parquet"
        write_parquet_atomic(frame, prediction_path)
        firewall_after = enforce_label_firewall(protocol)
        prediction_artifact = artifact(
            prediction_path, role="sealed_v3_probability_prediction"
        )
        spec_artifact = artifact(spec_path, role="frozen_baseline_model_spec")
        report = {
            "schema": "gwm_bench.runtime_r2_prediction_run.v1",
            "suite_id": protocol["suite_id"],
            "model_group": model_id,
            "status": "PREDICTION_COMPLETE_LABEL_FIREWALL_INTACT",
            "created_at": utc_now(),
            "lifecycle": {
                "prepare": "complete",
                "predict": "complete",
                "writeback": "predicted_probability_state_only",
                "audit": "complete",
            },
            "label_firewall": {
                "before": firewall_before,
                "after": firewall_after,
                "target_pixels_read": False,
            },
            "contract": {
                "submission_contract_sha256": sha256_file(
                    SUBMISSION_CONTRACT_PATH
                ),
                "protocol_sha256": sha256_file(PROTOCOL_PATH),
                "phase_a_bundle_fingerprint": bundle_manifest[
                    "bundle_fingerprint"
                ],
                "submission_keys_sha256": bundle_manifest["artifacts"][
                    "submission_keys.parquet"
                ]["sha256"],
            },
            "hashes": {
                "protocol": sha256_file(PROTOCOL_PATH),
                "phase_a_bundle": bundle_manifest["bundle_fingerprint"],
                "runtime_environment": runtime_artifact["sha256"],
                "adapter_source": source_artifact["sha256"],
                "model_or_binary": spec_artifact["sha256"],
                "random_seed_or_seed_set": fingerprint(
                    {"deterministic": True, "seeds": []}
                ),
                "prediction": prediction_artifact["sha256"],
            },
            "artifacts": {
                "prediction": prediction_artifact,
                "model_spec": spec_artifact,
                "adapter_source": source_artifact,
                "runtime_environment": runtime_artifact,
                "development_sources": (
                    None
                    if model_id == "state_persistence"
                    else development_artifact
                ),
            },
            "prediction_summary": prediction_summary(frame, inputs),
            "resource_usage": {
                "wall_time_seconds": time.perf_counter() - model_started,
                "peak_memory_bytes": peak_memory_bytes(),
                "temporary_bytes": prediction_path.stat().st_size,
                "exit_status": 0,
            },
            "replay": {
                "deterministic_candidate": True,
                "required": True,
                "verified": False,
                "note": "verified is set only by the independent replay command",
            },
            "claim_boundary": {
                "baseline_only": True,
                "model_quality_claimed_before_labels": False,
                "operational_forecast_supported": False,
            },
        }
        report_path = model_root / "run_report.json"
        write_json_atomic(report, report_path)
        reports[model_id] = {
            "prediction": prediction_artifact,
            "run_report": artifact(report_path, role="runtime_r2_run_report"),
        }
        print(
            f"{model_id}: rows={len(frame)} sha256={prediction_artifact['sha256']}",
            flush=True,
        )

    summary = {
        "schema": "gwm_bench.v3_internal_baselines.v1",
        "suite_id": protocol["suite_id"],
        "status": "THREE_INTERNAL_BASELINES_COMPLETE_REPLAY_PENDING",
        "created_at": utc_now(),
        "phase_a_bundle_fingerprint": bundle_manifest["bundle_fingerprint"],
        "target_pixels_read": False,
        "target_file_count": 0,
        "reports": reports,
        "total_wall_time_seconds": time.perf_counter() - started,
    }
    summary_path = output_root / "internal_baselines_report.json"
    write_json_atomic(summary, summary_path)
    print(f"summary: {summary_path}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    run(args.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
