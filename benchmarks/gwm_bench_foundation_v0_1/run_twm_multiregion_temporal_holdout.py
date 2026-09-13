#!/usr/bin/env python3
"""Commit five-year TWM predictions before scoring 19 new region label stacks."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.build_baselines_and_controls import (
    _transition_matrix,
)
from benchmarks.gwm_bench_foundation_v0_1.freeze_multiregion_temporal_holdout import (
    DEFAULT_OUTPUT as DEFAULT_PROTOCOL,
    PREDICTION_YEARS,
)
from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
)
from benchmarks.gwm_bench_foundation_v0_1.run_twm_observed_scenario import (
    TWM_CLASS_COUNT,
    _fit_foundation_model,
    _inference_sequences,
    _roll_calibrated_probabilities,
    _stack_sequences,
    _train_sequences,
)
from benchmarks.gwm_bench_foundation_v0_1.run_twm_shanghai_temporal_holdout import (
    _continuation_batch,
    _roll_from_probability,
)
from data_agent.uwm.dam_geospatial_kernel.twm_sequence_benchmark import (
    _kernel_config,
)
from data_agent.uwm.dam_geospatial_kernel.twm_transition_head import (
    TWMLandTransitionModel,
)


BENCHMARK_ROOT = Path(__file__).resolve().parent
DEVELOPMENT_ROOT = BENCHMARK_ROOT / "development"
DEFAULT_OUTPUT_ROOT = DEVELOPMENT_ROOT / "multiregion_temporal_holdout/twm"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_repo_artifact(artifact: dict[str, Any]) -> Path:
    path = REPO_ROOT / artifact["path"]
    if not path.is_file() or path.stat().st_size != int(artifact["size_bytes"]):
        raise ValueError(f"sealed_input_artifact_mismatch:{path}")
    if _sha256(path) != artifact["sha256"]:
        raise ValueError(f"sealed_input_hash_mismatch:{path}")
    return path


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def _prediction_frame(
    *,
    fold_index: int,
    sequences: list[Any],
    probabilities: np.ndarray,
) -> pd.DataFrame:
    rows = []
    offset = 0
    for sequence in sequences:
        count = int(sequence.metadata["fine_node_count"])
        region_probability = probabilities[offset : offset + count]
        offset += count
        for node_index, node_id in enumerate(sequence.node_ids):
            for year_index, target_year in enumerate(PREDICTION_YEARS):
                row = {
                    "fold_index": fold_index,
                    "region_id": sequence.metadata["region_id"],
                    "node_id": node_id,
                    "target_year": target_year,
                }
                row.update(
                    dict(
                        zip(
                            PROBABILITY_COLUMNS,
                            region_probability[node_index, year_index].tolist(),
                        )
                    )
                )
                rows.append(row)
    if offset != probabilities.shape[0]:
        raise ValueError("multiregion_prediction_node_count_mismatch")
    frame = pd.DataFrame(rows, columns=KEY_COLUMNS + PROBABILITY_COLUMNS)
    return frame.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)


def _predict_five_years(
    *, model: TWMLandTransitionModel, sequences: list[Any], shared_offset: float
) -> np.ndarray:
    stacked = _stack_sequences(sequences)
    fine_slices = []
    offset = 0
    for sequence in sequences:
        count = int(sequence.metadata["fine_node_count"])
        fine_slices.append(slice(offset, offset + count))
        offset += count
    model.eval()
    with torch.no_grad():
        first_output = model(stacked.batch)
        first = _roll_calibrated_probabilities(
            output=first_output,
            fine_node_mask=stacked.fine_node_mask,
            initial_class=stacked.initial_class,
            offsets=(shared_offset, shared_offset, shared_offset),
        )
        continuation_sequences = [
            replace(
                sequence,
                batch=_continuation_batch(
                    sequence=sequence,
                    fine_probability_2023=first[sequence_slice, 2],
                ),
            )
            for sequence, sequence_slice in zip(sequences, fine_slices)
        ]
        continuation = _stack_sequences(continuation_sequences)
        later_output = model(continuation.batch)
        later = _roll_from_probability(
            output=later_output,
            fine_node_mask=continuation.fine_node_mask,
            initial_probability=first[:, 2],
            shared_offset=shared_offset,
        )
        probability = torch.cat([first, later[:, :2]], dim=1)
    return probability.cpu().numpy().astype(np.float64)


def _baseline_fold_frame(
    *,
    fold_index: int,
    fold_inputs: pd.DataFrame,
    train: pd.DataFrame,
    edges: pd.DataFrame,
    spatial: bool,
) -> pd.DataFrame:
    transition = _transition_matrix(train, fold_index) if spatial else None
    rows = []
    for region_id, region_inputs in fold_inputs.groupby("region_id", sort=True):
        region_inputs = region_inputs.sort_values("node_id", kind="mergesort")
        node_ids = region_inputs["node_id"].tolist()
        state = np.eye(TWM_CLASS_COUNT, dtype=np.float64)[
            region_inputs["land_class_2020"].to_numpy(dtype=np.int64)
        ]
        neighbors: list[list[int]] = [[] for _ in node_ids]
        if spatial:
            node_index = {node_id: index for index, node_id in enumerate(node_ids)}
            for edge in edges[edges["region_id"] == region_id].itertuples(index=False):
                source = node_index.get(edge.source_node_id)
                target = node_index.get(edge.target_node_id)
                if source is not None and target is not None:
                    neighbors[source].append(target)
        for target_year in PREDICTION_YEARS:
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
                    "fold_index": fold_index,
                    "region_id": region_id,
                    "node_id": node_id,
                    "target_year": target_year,
                }
                row.update(dict(zip(PROBABILITY_COLUMNS, state[index].tolist())))
                rows.append(row)
    return pd.DataFrame(rows, columns=KEY_COLUMNS + PROBABILITY_COLUMNS)


def _validate_full_prediction(frame: pd.DataFrame, expected_rows: int) -> pd.DataFrame:
    frame = frame.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    if len(frame) != expected_rows or frame.duplicated(KEY_COLUMNS).any():
        raise ValueError("incomplete_or_duplicate_multiregion_prediction")
    values = frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    if not np.isfinite(values).all() or np.any((values < 0.0) | (values > 1.0)):
        raise ValueError("invalid_multiregion_prediction_probability")
    if not np.allclose(values.sum(axis=1), 1.0, atol=1e-6, rtol=0.0):
        raise ValueError("multiregion_prediction_rows_do_not_sum_to_one")
    return frame


def run_twm_multiregion_temporal_holdout(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    protocol_path = protocol_path.resolve()
    output_root = output_root.resolve()
    protocol = _load_json(protocol_path)
    if protocol["status"] != "sealed_before_19_region_label_scoring":
        raise ValueError("multiregion_temporal_protocol_is_not_sealed")
    # Never verify or open label_artifacts in this predictor.
    for artifact in protocol["input_artifacts"]:
        _verify_repo_artifact(artifact)
    for member in protocol["twm_candidate"]["members"]:
        _verify_repo_artifact(member["development_report"])
        _verify_repo_artifact(member["preexisting_fold0_weights"])

    train = pd.read_parquet(DEVELOPMENT_ROOT / "observed_train.parquet")
    inputs = pd.read_parquet(DEVELOPMENT_ROOT / "observed_inputs.parquet")
    edges = pd.read_parquet(DEVELOPMENT_ROOT / "observed_edges.parquet")
    folds = _load_json(DEVELOPMENT_ROOT / "region_folds.json")["folds"]
    members_by_seed = {
        int(member["seed"]): member for member in protocol["twm_candidate"]["members"]
    }
    frames_by_seed: dict[int, list[pd.DataFrame]] = {
        seed: [] for seed in members_by_seed
    }
    weights_by_seed: dict[int, list[dict[str, Any]]] = {
        seed: [] for seed in members_by_seed
    }
    baseline_frames = {"persistence": [], "fixed_adjacency": []}
    output_root.mkdir(parents=True, exist_ok=True)

    for fold in folds:
        fold_index = int(fold["fold_index"])
        fold_train = train[train["fold_index"] == fold_index]
        fold_test = inputs[
            (inputs["fold_index"] == fold_index) & (inputs["split"] == "test")
        ]
        sequences = _inference_sequences(fold_inputs=fold_test, edges=edges)
        stacked_train = _stack_sequences(
            _train_sequences(fold_train=fold_train, edges=edges)
        )
        for seed, member in members_by_seed.items():
            if fold_index == 0:
                model = TWMLandTransitionModel(
                    _kernel_config(
                        state_writeback_mode="categorical_mixture",
                        context_dim=stacked_train.batch.node_context.shape[1],
                    )
                )
                source_weights = _verify_repo_artifact(
                    member["preexisting_fold0_weights"]
                )
                model.load_state_dict(
                    torch.load(source_weights, map_location="cpu", weights_only=True)
                )
                weight_artifact = {
                    "fold_index": fold_index,
                    "path": str(source_weights.relative_to(BENCHMARK_ROOT)),
                    "sha256": _sha256(source_weights),
                    "reused_preexisting_weight": True,
                }
            else:
                model = _fit_foundation_model(
                    train=stacked_train,
                    state_writeback_mode="categorical_mixture",
                    seed=seed,
                    epochs=int(member["epochs"]),
                    training_objective="legacy_change_focal",
                    change_sample_weight=3.0,
                    kernel_variant="full",
                )
                weights_path = output_root / f"seed_{seed}/fold_{fold_index}_weights.pt"
                weights_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = weights_path.with_suffix(".pt.tmp")
                torch.save(model.state_dict(), temporary)
                temporary.replace(weights_path)
                weight_artifact = {
                    "fold_index": fold_index,
                    "path": str(weights_path.relative_to(BENCHMARK_ROOT)),
                    "sha256": _sha256(weights_path),
                    "reused_preexisting_weight": False,
                }
            probability = _predict_five_years(
                model=model,
                sequences=sequences,
                shared_offset=float(
                    member["shared_change_logit_offset_by_fold"][str(fold_index)]
                ),
            )
            frames_by_seed[seed].append(
                _prediction_frame(
                    fold_index=fold_index,
                    sequences=sequences,
                    probabilities=probability,
                )
            )
            weights_by_seed[seed].append(weight_artifact)
        baseline_frames["persistence"].append(
            _baseline_fold_frame(
                fold_index=fold_index,
                fold_inputs=fold_test,
                train=train,
                edges=edges,
                spatial=False,
            )
        )
        baseline_frames["fixed_adjacency"].append(
            _baseline_fold_frame(
                fold_index=fold_index,
                fold_inputs=fold_test,
                train=train,
                edges=edges,
                spatial=True,
            )
        )
        print(f"completed multiregion temporal fold={fold_index}", flush=True)

    expected_rows = int((inputs["split"] == "test").sum()) * len(PREDICTION_YEARS)
    member_frames = []
    member_reports = []
    for seed, fold_frames in frames_by_seed.items():
        frame = _validate_full_prediction(
            pd.concat(fold_frames, ignore_index=True), expected_rows
        )
        path = output_root / f"seed_{seed}/prediction_2021_2025.parquet"
        _write_parquet(frame, path)
        member_frames.append(frame)
        member_reports.append(
            {
                "seed": seed,
                "prediction": {
                    "path": str(path.relative_to(BENCHMARK_ROOT)),
                    "sha256": _sha256(path),
                    "row_count": len(frame),
                },
                "weights": weights_by_seed[seed],
            }
        )
    reference_keys = member_frames[0][KEY_COLUMNS]
    if any(
        not frame[KEY_COLUMNS].equals(reference_keys) for frame in member_frames[1:]
    ):
        raise ValueError("multiregion_member_prediction_keys_mismatch")
    ensemble = reference_keys.copy()
    ensemble[PROBABILITY_COLUMNS] = np.mean(
        np.stack(
            [frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64) for frame in member_frames]
        ),
        axis=0,
    )
    ensemble = _validate_full_prediction(ensemble, expected_rows)
    prediction_path = output_root / "twm_prediction_2021_2025.parquet"
    _write_parquet(ensemble, prediction_path)

    baseline_artifacts = {}
    for name, fold_frames in baseline_frames.items():
        frame = _validate_full_prediction(
            pd.concat(fold_frames, ignore_index=True), expected_rows
        )
        path = output_root / f"{name}_prediction_2021_2025.parquet"
        _write_parquet(frame, path)
        baseline_artifacts[name] = {
            "path": str(path.relative_to(BENCHMARK_ROOT)),
            "sha256": _sha256(path),
            "row_count": len(frame),
        }

    report = {
        "schema": "gwm_bench.multiregion_twm_temporal_prediction.v1",
        "protocol_id": protocol["protocol_id"],
        "status": "all_region_predictions_committed_before_19_region_scoring",
        "prediction_years": list(PREDICTION_YEARS),
        "scored_regions": protocol["scored_regions"],
        "excluded_regions": protocol["excluded_regions"],
        "protocol": {
            "path": str(protocol_path.relative_to(BENCHMARK_ROOT)),
            "sha256": _sha256(protocol_path),
        },
        "candidate": {
            "name": "frozen current-source three-seed TWM",
            "member_seeds": sorted(members_by_seed),
            "fold_count": len(folds),
            "future_observed_land_or_viirs_used": False,
            "shanghai_holdout_score_used_for_configuration_or_training": False,
        },
        "members": member_reports,
        "artifacts": {
            "prediction": {
                "path": str(prediction_path.relative_to(BENCHMARK_ROOT)),
                "sha256": _sha256(prediction_path),
                "row_count": len(ensemble),
            },
            "baselines": baseline_artifacts,
        },
        "integrity": {
            "2024_2025_label_rasters_opened": False,
            "all_prediction_hashes_committed": True,
            "fold0_weights_fixed_before_shanghai_scoring": True,
            "fold1_4_configuration_unchanged_after_shanghai_scoring": True,
        },
        "claim_boundary": protocol["claim_boundary"],
    }
    report_path = output_root / "prediction_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "row_count": len(ensemble),
                "prediction_sha256": report["artifacts"]["prediction"]["sha256"],
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    run_twm_multiregion_temporal_holdout(
        protocol_path=args.protocol, output_root=args.output_root
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
