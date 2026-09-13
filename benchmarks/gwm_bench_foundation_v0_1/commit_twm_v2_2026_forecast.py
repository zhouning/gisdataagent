#!/usr/bin/env python3
"""Precommit the frozen TWM V2 2026 forecast before annual labels exist."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch.nn import functional as functional


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.build_baselines_and_controls import (
    _transition_matrix,
)
from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
)
from benchmarks.gwm_bench_foundation_v0_1.run_twm_multiregion_posthoc_v2 import (
    DEFAULT_OUTPUT_ROOT as V2_ROOT,
    TWM_CLASS_COUNT,
    _rate_capped_update,
    _recursive_batch,
    _sha256,
)
from benchmarks.gwm_bench_foundation_v0_1.run_twm_observed_scenario import (
    TRAIN_YEARS,
    _build_region_sequence,
    _neighbor_indices,
)
from data_agent.uwm.dam_geospatial_kernel.twm_sequence_benchmark import (
    _kernel_config,
)
from data_agent.uwm.dam_geospatial_kernel.twm_transition_head import (
    TWMLandTransitionModel,
)


BENCHMARK_ROOT = Path(__file__).resolve().parent
DEVELOPMENT_ROOT = BENCHMARK_ROOT / "development"
DEFAULT_OUTPUT_ROOT = (
    DEVELOPMENT_ROOT / "multiregion_temporal_holdout/twm_v2_frozen_2026"
)
FORECAST_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
SCORED_YEAR = 2026
SOURCE_DEPENDENCIES = (
    BENCHMARK_ROOT / "build_baselines_and_controls.py",
    BENCHMARK_ROOT / "observed_evaluator.py",
    BENCHMARK_ROOT / "run_twm_multiregion_posthoc_v2.py",
    BENCHMARK_ROOT / "run_twm_observed_scenario.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/twm_adapter.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/twm_sequence_adapter.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/model.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/contracts.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/twm_transition_head.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/twm_sequence_benchmark.py",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact(path: Path, *, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "role": role,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _v2_artifact_path(artifact: dict[str, Any]) -> Path:
    if artifact.get("path_scope") != "benchmark_relative":
        raise ValueError("frozen_v2_artifact_must_be_benchmark_relative")
    path = (BENCHMARK_ROOT / artifact["path"]).resolve()
    if (
        not path.is_file()
        or path.stat().st_size != int(artifact["size_bytes"])
        or _sha256(path) != artifact["sha256"]
    ):
        raise ValueError(f"frozen_v2_artifact_mismatch:{path}")
    return path


def _verify_v2_report(report: dict[str, Any]) -> None:
    if report["status"] != "posthoc_development_prediction_complete":
        raise ValueError("v2_development_candidate_is_not_complete")
    if report["candidate"]["labels_2021_2025_used_for_training_or_selection"]:
        raise ValueError("v2_candidate_used_future_labels_for_selection")
    _v2_artifact_path(report["source"])
    for member in report["members"]:
        _v2_artifact_path(member["prediction"])
        for fold in member["folds"]:
            _v2_artifact_path(fold["weights"])
            _v2_artifact_path(fold["selection_trials"])
    _v2_artifact_path(report["artifacts"]["prediction"])


def _prediction_frame(
    *, fold_index: int, region_id: str, node_ids: list[str], probability: np.ndarray
) -> pd.DataFrame:
    if probability.shape != (len(node_ids), len(FORECAST_YEARS), TWM_CLASS_COUNT):
        raise ValueError("twm_v2_2026_probability_shape_mismatch")
    rows = []
    for node_index, node_id in enumerate(node_ids):
        for year_index, target_year in enumerate(FORECAST_YEARS):
            row = {
                "fold_index": fold_index,
                "region_id": region_id,
                "node_id": node_id,
                "target_year": target_year,
            }
            row.update(
                dict(
                    zip(
                        PROBABILITY_COLUMNS,
                        probability[node_index, year_index].tolist(),
                    )
                )
            )
            rows.append(row)
    return pd.DataFrame(rows, columns=KEY_COLUMNS + PROBABILITY_COLUMNS)


def _validate_prediction(frame: pd.DataFrame, *, expected_rows: int) -> pd.DataFrame:
    frame = frame.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    if len(frame) != expected_rows or frame.duplicated(KEY_COLUMNS).any():
        raise ValueError("incomplete_or_duplicate_twm_v2_2026_prediction")
    values = frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    if not np.isfinite(values).all() or np.any((values < 0.0) | (values > 1.0)):
        raise ValueError("invalid_twm_v2_2026_probability")
    if not np.allclose(values.sum(axis=1), 1.0, atol=1e-6, rtol=0.0):
        raise ValueError("twm_v2_2026_probability_rows_do_not_sum_to_one")
    return frame


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def _roll_region(
    *,
    model: TWMLandTransitionModel,
    frame: pd.DataFrame,
    region_edges: pd.DataFrame,
    logit_offset: float,
    cap_rate: float,
) -> np.ndarray:
    frame = frame.sort_values("node_id", kind="mergesort").reset_index(drop=True)
    sequence = _build_region_sequence(
        frame=frame,
        region_edges=region_edges,
        initial_year=2020,
        target_years=(2021,),
        future_class_by_year=None,
    )
    neighbors = _neighbor_indices(
        node_ids=frame["node_id"].tolist(), region_edges=region_edges
    )
    probability_by_year = {
        year: functional.one_hot(
            torch.tensor(
                frame[f"land_class_{year}"].to_numpy(dtype=np.int64),
                dtype=torch.long,
            ),
            num_classes=TWM_CLASS_COUNT,
        ).float()
        for year in TRAIN_YEARS
    }
    probabilities = []
    model.eval()
    with torch.no_grad():
        for target_year in FORECAST_YEARS:
            feature_year = target_year - 1
            batch = _recursive_batch(
                sequence=sequence,
                frame=frame,
                probability_by_year=probability_by_year,
                neighbors=neighbors,
                feature_year=feature_year,
            )
            output = model(batch)
            fine_count = int(sequence.metadata["fine_node_count"])
            probability_by_year[target_year] = _rate_capped_update(
                current_probability=probability_by_year[feature_year],
                change_logit=output.change_logit[:fine_count],
                destination_logits=output.destination_logits[:fine_count],
                logit_offset=logit_offset,
                cap_rate=cap_rate,
                group_sizes=[fine_count],
            )
            probabilities.append(probability_by_year[target_year])
    return torch.stack(probabilities, dim=1).cpu().numpy().astype(np.float64)


def _predict_fold(
    *,
    model: TWMLandTransitionModel,
    fold_index: int,
    fold_inputs: pd.DataFrame,
    edges: pd.DataFrame,
    logit_offset: float,
    cap_rate: float,
) -> pd.DataFrame:
    frames = []
    for region_id, region_frame in fold_inputs.groupby("region_id", sort=True):
        region_frame = region_frame.sort_values(
            "node_id", kind="mergesort"
        ).reset_index(drop=True)
        probability = _roll_region(
            model=model,
            frame=region_frame,
            region_edges=edges[edges["region_id"] == region_id],
            logit_offset=logit_offset,
            cap_rate=cap_rate,
        )
        frames.append(
            _prediction_frame(
                fold_index=fold_index,
                region_id=region_id,
                node_ids=region_frame["node_id"].tolist(),
                probability=probability,
            )
        )
    return pd.concat(frames, ignore_index=True)


def _baseline_frame(
    *,
    inputs: pd.DataFrame,
    train: pd.DataFrame,
    edges: pd.DataFrame,
    spatial: bool,
) -> pd.DataFrame:
    rows = []
    for (fold_index, region_id), region_inputs in inputs.groupby(
        ["fold_index", "region_id"], sort=True
    ):
        region_inputs = region_inputs.sort_values("node_id", kind="mergesort")
        node_ids = region_inputs["node_id"].tolist()
        state = np.eye(TWM_CLASS_COUNT, dtype=np.float64)[
            region_inputs["land_class_2020"].to_numpy(dtype=np.int64)
        ]
        transition = (
            _transition_matrix(train, int(fold_index)) if spatial else None
        )
        neighbors: list[list[int]] = [[] for _ in node_ids]
        if spatial:
            node_index = {node_id: index for index, node_id in enumerate(node_ids)}
            for edge in edges[edges["region_id"] == region_id].itertuples(index=False):
                source = node_index.get(edge.source_node_id)
                target = node_index.get(edge.target_node_id)
                if source is not None and target is not None:
                    neighbors[source].append(target)
        for target_year in FORECAST_YEARS:
            if spatial:
                neighbor_state = np.stack(
                    [
                        state[indices].mean(axis=0) if indices else state[index]
                        for index, indices in enumerate(neighbors)
                    ]
                )
                state = 0.5 * (state @ transition) + 0.5 * (
                    neighbor_state @ transition
                )
                state /= state.sum(axis=1, keepdims=True)
            for index, node_id in enumerate(node_ids):
                row = {
                    "fold_index": int(fold_index),
                    "region_id": region_id,
                    "node_id": node_id,
                    "target_year": target_year,
                }
                row.update(dict(zip(PROBABILITY_COLUMNS, state[index].tolist())))
                rows.append(row)
    return pd.DataFrame(rows, columns=KEY_COLUMNS + PROBABILITY_COLUMNS)


def _candidate_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def commit_twm_v2_2026_forecast(
    *, output_root: Path = DEFAULT_OUTPUT_ROOT
) -> dict[str, Any]:
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    v2_report_path = V2_ROOT / "prediction_report.json"
    v2_report = _load_json(v2_report_path)
    _verify_v2_report(v2_report)
    inputs = pd.read_parquet(DEVELOPMENT_ROOT / "observed_inputs.parquet")
    test_inputs = inputs[inputs["split"] == "test"].copy()
    train = pd.read_parquet(DEVELOPMENT_ROOT / "observed_train.parquet")
    edges = pd.read_parquet(DEVELOPMENT_ROOT / "observed_edges.parquet")
    folds = _load_json(DEVELOPMENT_ROOT / "region_folds.json")["folds"]
    expected_rows = len(test_inputs) * len(FORECAST_YEARS)

    member_frames = []
    committed_members = []
    for member in v2_report["members"]:
        seed = int(member["seed"])
        fold_by_index = {
            int(row["fold_index"]): row for row in member["folds"]
        }
        frames = []
        committed_folds = []
        for fold in folds:
            fold_index = int(fold["fold_index"])
            fold_report = fold_by_index[fold_index]
            weights_path = _v2_artifact_path(fold_report["weights"])
            model = TWMLandTransitionModel(
                _kernel_config(
                    state_writeback_mode="categorical_mixture",
                    context_dim=12,
                    horizon=1,
                )
            )
            model.load_state_dict(
                torch.load(weights_path, map_location="cpu", weights_only=True)
            )
            fold_inputs = test_inputs[test_inputs["fold_index"] == fold_index]
            selected = fold_report["selected"]
            frames.append(
                _predict_fold(
                    model=model,
                    fold_index=fold_index,
                    fold_inputs=fold_inputs,
                    edges=edges,
                    logit_offset=float(selected["logit_offset"]),
                    cap_rate=float(selected["cap_rate"]),
                )
            )
            committed_folds.append(
                {
                    "fold_index": fold_index,
                    "weights": fold_report["weights"],
                    "selection_trials": fold_report["selection_trials"],
                    "selected_logit_offset": float(selected["logit_offset"]),
                    "selected_cap_rate": float(selected["cap_rate"]),
                }
            )
        member_frame = _validate_prediction(
            pd.concat(frames, ignore_index=True), expected_rows=expected_rows
        )
        member_path = output_root / f"seed_{seed}_prediction_2021_2026.parquet"
        _write_parquet(member_frame, member_path)
        member_frames.append(member_frame)
        committed_members.append(
            {
                "seed": seed,
                "folds": committed_folds,
                "prediction": _artifact(
                    member_path, role="precommitted_2021_2026_member_prediction"
                ),
            }
        )
        print(f"committed frozen V2 2026 member seed={seed}", flush=True)

    keys = member_frames[0][KEY_COLUMNS]
    if any(not frame[KEY_COLUMNS].equals(keys) for frame in member_frames[1:]):
        raise ValueError("twm_v2_2026_member_keys_mismatch")
    ensemble = keys.copy()
    ensemble[PROBABILITY_COLUMNS] = np.mean(
        np.stack(
            [frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64) for frame in member_frames]
        ),
        axis=0,
    )
    ensemble = _validate_prediction(ensemble, expected_rows=expected_rows)
    prediction_path = output_root / "twm_v2_prediction_2021_2026.parquet"
    _write_parquet(ensemble, prediction_path)

    baseline_artifacts = {}
    for name, spatial in (("persistence", False), ("fixed_adjacency", True)):
        baseline = _validate_prediction(
            _baseline_frame(
                inputs=test_inputs, train=train, edges=edges, spatial=spatial
            ),
            expected_rows=expected_rows,
        )
        path = output_root / f"{name}_prediction_2021_2026.parquet"
        _write_parquet(baseline, path)
        baseline_artifacts[name] = _artifact(
            path, role=f"precommitted_2026_{name}_baseline"
        )

    source_artifacts = [
        _artifact(Path(__file__), role="2026_precommit_program"),
        *[
            _artifact(path, role="frozen_prediction_dependency")
            for path in SOURCE_DEPENDENCIES
        ],
    ]
    input_artifacts = [
        _artifact(v2_report_path, role="frozen_v2_development_report"),
        *[
            _artifact(DEVELOPMENT_ROOT / name, role="frozen_model_input")
            for name in (
                "bundle_manifest.json",
                "region_folds.json",
                "observed_train.parquet",
                "observed_inputs.parquet",
                "observed_edges.parquet",
            )
        ],
    ]
    prediction_artifact = _artifact(
        prediction_path, role="precommitted_2021_2026_ensemble_prediction"
    )
    identity_material = {
        "source_hashes": [row["sha256"] for row in source_artifacts],
        "input_hashes": [row["sha256"] for row in input_artifacts],
        "weight_hashes": [
            fold["weights"]["sha256"]
            for member in committed_members
            for fold in member["folds"]
        ],
        "selection_hashes": [
            fold["selection_trials"]["sha256"]
            for member in committed_members
            for fold in member["folds"]
        ],
        "prediction_sha256": prediction_artifact["sha256"],
    }
    scored_regions = sorted(test_inputs["region_id"].unique().tolist())
    report = {
        "schema": "gwm_bench.twm_v2_2026_candidate_precommit.v1",
        "protocol_id": "TWM-V2-TEMPORAL-2026-PRECOMMIT-v1",
        "status": "candidate_and_predictions_sealed_before_2026_labels",
        "candidate_fingerprint": _candidate_fingerprint(identity_material),
        "forecast_origin_year": 2020,
        "prediction_years": list(FORECAST_YEARS),
        "scored_year": SCORED_YEAR,
        "scored_regions": scored_regions,
        "candidate": {
            **v2_report["candidate"],
            "weights_retrained_for_2026": False,
            "parameters_reselected_for_2026": False,
            "member_count": len(committed_members),
            "fold_count": len(folds),
        },
        "members": committed_members,
        "artifacts": {
            "prediction": prediction_artifact,
            "baselines": baseline_artifacts,
            "source": source_artifacts,
            "inputs": input_artifacts,
        },
        "hidden_label_registration": {
            "status": "not_yet_available",
            "required_source": "GOOGLE/DYNAMICWORLD/V1 annual mode label",
            "required_observation_window_utc": [
                "2026-01-01T00:00:00Z",
                "2027-01-01T00:00:00Z",
            ],
            "earliest_valid_export_date": "2027-01-01",
            "required_years": [2025, 2026],
            "required_region_count": len(scored_regions),
            "required_grid": "exact match to each frozen 2020 reference raster",
            "pixel_values_opened_during_precommit": False,
        },
        "evaluation_protocol": {
            "primary_metric": "unweighted_mean_of_20_region_2026_change_f1",
            "secondary_metrics": [
                "overall_change_f1",
                "changed_destination_macro_f1",
                "overall_class_macro_f1",
                "multiclass_brier_score",
                "predicted_to_observed_change_ratio",
            ],
            "predicted_change": "committed_2026_argmax_differs_from_committed_2025_argmax",
            "observed_change": "hidden_2026_class_differs_from_registered_2025_class",
            "zero_denominator_change_f1": 1.0,
            "no_single_composite_score": True,
            "data_sufficiency": {
                "minimum_total_observed_changes": 20,
                "minimum_regions_with_at_least_one_observed_change": 10,
                "failure_effect": "inconclusive_not_pass_or_fail",
            },
            "acceptance_gates_all_required": [
                "primary_metric_strictly_exceeds_both_precommitted_baselines",
                "overall_change_f1_strictly_exceeds_both_precommitted_baselines",
                "overall_change_f1_at_least_0.15",
                "overall_class_macro_f1_at_least_persistence",
                "multiclass_brier_score_no_greater_than_persistence",
                "predicted_to_observed_change_ratio_between_0.5_and_1.75",
            ],
        },
        "integrity": {
            "v2_source_hash_verified": True,
            "all_15_weight_hashes_verified": True,
            "all_15_selection_trial_hashes_verified": True,
            "2026_label_manifest_accessed": False,
            "2026_label_pixels_accessed": False,
            "prediction_hash_committed_before_labels": True,
            "post_commit_model_or_threshold_changes_allowed": False,
        },
        "claim_boundary": {
            "on_pass": "bounded_2026_temporal_generalization_on_20_existing_regions",
            "new_geography_generalization": False,
            "operational_forecast_validation": False,
            "general_twm_supported": False,
            "general_gwm_supported": False,
        },
    }
    report_path = output_root / "precommit_protocol.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "candidate_fingerprint": report["candidate_fingerprint"],
                "prediction_sha256": prediction_artifact["sha256"],
                "prediction_rows": len(ensemble),
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    commit_twm_v2_2026_forecast(output_root=args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
