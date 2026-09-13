#!/usr/bin/env python3
"""Train and run the post-hoc TWM V2 one-year recursive candidate.

This is a development experiment. The 2024-2025 labels were already opened
before this candidate was created, so its score cannot be reported as a blind
holdout result. Model fitting and parameter selection nevertheless use only the
2017-2020 bundle; the later labels are not opened by this predictor.
"""

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
from torch.nn import functional as functional


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.freeze_multiregion_temporal_holdout import (
    DEFAULT_OUTPUT as DEFAULT_PROTOCOL,
    PREDICTION_YEARS,
)
from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
)
from benchmarks.gwm_bench_foundation_v0_1.run_twm_multiregion_temporal_holdout import (
    DEFAULT_OUTPUT_ROOT as V1_OUTPUT_ROOT,
    _prediction_frame,
    _sha256,
    _validate_full_prediction,
    _write_parquet,
)
from benchmarks.gwm_bench_foundation_v0_1.run_twm_observed_scenario import (
    CONTEXT_DIM,
    TRAIN_YEARS,
    TWM_CLASS_COUNT,
    _build_region_sequence,
    _hierarchy,
    _neighbor_indices,
    _stack_sequences,
    _training_region_wide,
)
from data_agent.uwm.dam_geospatial_kernel.contracts import DAMGKBatch
from data_agent.uwm.dam_geospatial_kernel.twm_adapter import (
    WEB_MERCATOR_HALF_WORLD_METERS,
    _transform_nightlight,
)
from data_agent.uwm.dam_geospatial_kernel.twm_sequence_benchmark import (
    _kernel_config,
    _one_step_loss,
)
from data_agent.uwm.dam_geospatial_kernel.twm_transition_head import (
    TWMLandTransitionModel,
)


BENCHMARK_ROOT = Path(__file__).resolve().parent
DEVELOPMENT_ROOT = BENCHMARK_ROOT / "development"
DEFAULT_OUTPUT_ROOT = DEVELOPMENT_ROOT / "multiregion_temporal_holdout/twm_v2_posthoc"
DEFAULT_SEEDS = (31, 47, 73)
DEFAULT_EPOCHS = 80
CALIBRATION_OFFSETS = tuple(np.arange(-1.0, 3.01, 0.5).tolist())
ANNUAL_WINDOWS = ((2017, 2018), (2018, 2019), (2019, 2020))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact(path: Path) -> dict[str, Any]:
    path = path.resolve()
    try:
        recorded_path = str(path.relative_to(BENCHMARK_ROOT))
        path_scope = "benchmark_relative"
    except ValueError:
        recorded_path = str(path)
        path_scope = "absolute_external_output"
    return {
        "path": recorded_path,
        "path_scope": path_scope,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _annual_sequences(
    *, frame: pd.DataFrame, edges: pd.DataFrame, long_layout: bool
) -> list[Any]:
    sequences = []
    groups = frame.groupby("region_id", sort=True)
    for region_id, region_frame in groups:
        wide = _training_region_wide(region_frame) if long_layout else region_frame
        wide = wide.sort_values("node_id", kind="mergesort").reset_index(drop=True)
        region_edges = edges[edges["region_id"] == region_id]
        future = {
            year: torch.tensor(
                wide[f"land_class_{year}"].to_numpy(dtype=np.int64),
                dtype=torch.long,
            )
            for year in TRAIN_YEARS[1:]
        }
        for initial_year, target_year in ANNUAL_WINDOWS:
            sequence = _build_region_sequence(
                frame=wide,
                region_edges=region_edges,
                initial_year=initial_year,
                target_years=(target_year,),
                future_class_by_year=future,
            )
            sequences.append(
                replace(
                    sequence,
                    metadata={
                        **sequence.metadata,
                        "training_window": [initial_year, target_year],
                    },
                )
            )
    return sequences


def _fit_one_year_model(
    *, train: Any, seed: int, epochs: int
) -> TWMLandTransitionModel:
    torch.manual_seed(seed)
    model = TWMLandTransitionModel(
        _kernel_config(
            state_writeback_mode="categorical_mixture",
            context_dim=train.batch.node_context.shape[1],
            horizon=1,
        )
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=2e-4)
    for _ in range(epochs):
        model.train()
        optimizer.zero_grad()
        output = model(train.batch)
        loss = _one_step_loss(output, train, 0)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
    return model


def _conditional_destination(
    *, destination_logits: torch.Tensor, current_probability: torch.Tensor
) -> torch.Tensor:
    """Normalize destination classes after excluding the current argmax class."""

    current_class = torch.argmax(current_probability, dim=-1)
    masked = destination_logits.clone()
    masked.scatter_(1, current_class[:, None], -torch.inf)
    return torch.softmax(masked, dim=-1)


def _rate_capped_update(
    *,
    current_probability: torch.Tensor,
    change_logit: torch.Tensor,
    destination_logits: torch.Tensor,
    logit_offset: float,
    cap_rate: float,
    group_sizes: list[int],
) -> torch.Tensor:
    """Apply at most round(cap_rate * nodes) candidate changes per region."""

    if not 0.0 <= cap_rate <= 1.0:
        raise ValueError("annual_change_cap_rate_out_of_range")
    if sum(group_sizes) != current_probability.shape[0]:
        raise ValueError("rate_cap_group_sizes_do_not_match_nodes")
    change_probability = torch.sigmoid(change_logit - float(logit_offset))
    destination = _conditional_destination(
        destination_logits=destination_logits,
        current_probability=current_probability,
    )
    proposal = (
        (1.0 - change_probability[:, None]) * current_probability
        + change_probability[:, None] * destination
    )
    proposal = proposal / proposal.sum(dim=-1, keepdim=True).clamp_min(1e-12)

    result = current_probability.clone()
    offset = 0
    for size in group_sizes:
        region_slice = slice(offset, offset + size)
        budget = min(size, max(0, int(round(cap_rate * size))))
        if budget:
            current_class = torch.argmax(
                current_probability[region_slice], dim=-1
            )
            proposed_current_mass = torch.gather(
                proposal[region_slice], 1, current_class[:, None]
            ).squeeze(1)
            score = 1.0 - proposed_current_mass
            selected = torch.topk(score, k=budget, largest=True).indices + offset
            result[selected] = proposal[selected]
        offset += size
    return result / result.sum(dim=-1, keepdim=True).clamp_min(1e-12)


def _binary_f1(predicted: np.ndarray, observed: np.ndarray) -> float:
    true_positive = int(np.sum(predicted & observed))
    false_positive = int(np.sum(predicted & ~observed))
    false_negative = int(np.sum(~predicted & observed))
    denominator = 2 * true_positive + false_positive + false_negative
    return 2 * true_positive / denominator if denominator else 1.0


def _macro_f1(predicted: np.ndarray, observed: np.ndarray) -> float:
    scores = []
    for class_index in sorted(set(predicted.tolist()) | set(observed.tolist())):
        predicted_class = predicted == class_index
        observed_class = observed == class_index
        denominator = (
            2 * int(np.sum(predicted_class & observed_class))
            + int(np.sum(predicted_class & ~observed_class))
            + int(np.sum(~predicted_class & observed_class))
        )
        if denominator:
            scores.append(
                2 * int(np.sum(predicted_class & observed_class)) / denominator
            )
    return float(np.mean(scores)) if scores else 1.0


def _selection_metrics(
    *, probability: torch.Tensor, validation: Any, group_sizes: list[int]
) -> dict[str, Any]:
    values = probability.detach().cpu().numpy().astype(np.float64)
    predicted = np.argmax(values, axis=1).astype(np.int64)
    initial = validation.initial_class.detach().cpu().numpy().astype(np.int64)
    observed = validation.future_class[:, 0].detach().cpu().numpy().astype(np.int64)
    predicted_change = predicted != initial
    observed_change = observed != initial
    group_f1 = []
    offset = 0
    for size in group_sizes:
        region_slice = slice(offset, offset + size)
        group_f1.append(
            _binary_f1(
                predicted_change[region_slice], observed_change[region_slice]
            )
        )
        offset += size
    targets = np.eye(TWM_CLASS_COUNT, dtype=np.float64)[observed]
    return {
        "mean_region_year_change_f1": float(np.mean(group_f1)),
        "overall_change_f1": _binary_f1(predicted_change, observed_change),
        "overall_class_macro_f1": _macro_f1(predicted, observed),
        "multiclass_brier_score": float(
            np.mean(np.sum(np.square(values - targets), axis=1))
        ),
        "predicted_change_count": int(predicted_change.sum()),
        "observed_change_count": int(observed_change.sum()),
    }


def _historical_cap_candidates(fold_train: pd.DataFrame) -> list[float]:
    rates = []
    for _, region_frame in fold_train.groupby("region_id", sort=True):
        wide = _training_region_wide(region_frame)
        for initial_year, target_year in ANNUAL_WINDOWS:
            rates.append(
                float(
                    np.mean(
                        wide[f"land_class_{initial_year}"].to_numpy()
                        != wide[f"land_class_{target_year}"].to_numpy()
                    )
                )
            )
    values = np.asarray(rates, dtype=np.float64)
    candidates = {
        0.0,
        float(np.quantile(values, 0.25)),
        float(np.quantile(values, 0.50)),
        float(np.mean(values)),
        float(np.quantile(values, 0.75)),
        float(np.quantile(values, 0.90)),
        min(1.0, 1.25 * float(np.mean(values))),
    }
    return sorted(round(value, 6) for value in candidates)


def _selection_rank(trial: dict[str, Any]) -> tuple[float, ...]:
    metrics = trial["metrics"]
    return (
        round(metrics["mean_region_year_change_f1"], 12),
        round(metrics["overall_change_f1"], 12),
        round(metrics["overall_class_macro_f1"], 12),
        -round(metrics["multiclass_brier_score"], 12),
        -abs(
            metrics["predicted_change_count"]
            - metrics["observed_change_count"]
        ),
        -round(trial["cap_rate"], 6),
        -abs(round(trial["logit_offset"], 6)),
    )


def _select_validation_configuration(
    *, model: TWMLandTransitionModel, validation_sequences: list[Any], cap_rates: list[float]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validation = _stack_sequences(validation_sequences)
    group_sizes = [int(row.metadata["fine_node_count"]) for row in validation_sequences]
    current = functional.one_hot(
        validation.initial_class, num_classes=TWM_CLASS_COUNT
    ).float()
    model.eval()
    with torch.no_grad():
        output = model(validation.batch)
        logits = output.change_logit[validation.fine_node_mask]
        destination_logits = output.destination_logits[validation.fine_node_mask]
        trials = []
        for logit_offset in CALIBRATION_OFFSETS:
            for cap_rate in cap_rates:
                probability = _rate_capped_update(
                    current_probability=current,
                    change_logit=logits,
                    destination_logits=destination_logits,
                    logit_offset=logit_offset,
                    cap_rate=cap_rate,
                    group_sizes=group_sizes,
                )
                trials.append(
                    {
                        "logit_offset": float(logit_offset),
                        "cap_rate": float(cap_rate),
                        "metrics": _selection_metrics(
                            probability=probability,
                            validation=validation,
                            group_sizes=group_sizes,
                        ),
                    }
                )
    best = max(trials, key=_selection_rank)
    return best, trials


def _dynamic_fine_context(
    *,
    frame: pd.DataFrame,
    probability_by_year: dict[int, torch.Tensor],
    neighbors: list[list[int]],
    feature_year: int,
    clock_year: int,
) -> torch.Tensor:
    """Recompute all land-history and neighborhood features from current state."""

    years = sorted(year for year in probability_by_year if year <= feature_year)
    if not years or years[-1] != feature_year:
        raise ValueError("dynamic_context_feature_year_is_not_available")
    history = [probability_by_year[year] for year in years]
    current = history[-1]
    if len(history) == 1:
        recent_change = torch.zeros(len(frame), dtype=torch.float32)
        cumulative_change = recent_change.clone()
    else:
        changes = torch.stack(
            [
                1.0 - torch.sum(previous * later, dim=1)
                for previous, later in zip(history[:-1], history[1:])
            ],
            dim=1,
        )
        recent_change = changes[:, -1]
        cumulative_change = changes.mean(dim=1)

    temporal_rows = []
    for node_index, adjacent in enumerate(neighbors):
        local_indices = [node_index, *adjacent]
        distribution = current[local_indices].mean(dim=0)
        entropy = -torch.sum(
            distribution * torch.log(distribution.clamp_min(1e-8))
        ) / np.log(TWM_CLASS_COUNT)
        neighbor_recent = (
            recent_change[adjacent].mean()
            if adjacent
            else recent_change[node_index]
        )
        same_class_share = torch.sum(current[node_index] * distribution)
        temporal_rows.append(
            torch.stack(
                [
                    recent_change[node_index],
                    cumulative_change[node_index],
                    neighbor_recent,
                    entropy,
                    distribution[6],
                    same_class_share,
                ]
            )
        )
    temporal = torch.stack(temporal_rows)

    coordinates = torch.tensor(
        frame[["x_3857", "y_3857"]].to_numpy(dtype=np.float32)
    )
    base = torch.zeros((len(frame), 4), dtype=torch.float32)
    base[:, :2] = (
        coordinates / WEB_MERCATOR_HALF_WORLD_METERS
    ).clamp(-1.0, 1.0)
    base[:, 3] = (clock_year - 2017) / 10.0
    viirs_current_year = min(feature_year, 2020)
    viirs_previous_year = min(feature_year - 1, 2020)
    viirs_current = torch.tensor(
        frame[f"viirs_nightlight_{viirs_current_year}"].to_numpy(dtype=np.float32)
    )
    viirs_previous = torch.tensor(
        frame[f"viirs_nightlight_{viirs_previous_year}"].to_numpy(dtype=np.float32)
    )
    viirs_level = _transform_nightlight(viirs_current)
    viirs_lag_change = viirs_level - _transform_nightlight(viirs_previous)
    context = torch.cat(
        [base, temporal, viirs_level[:, None], viirs_lag_change[:, None]], dim=1
    )
    if context.shape[1] != CONTEXT_DIM:
        raise ValueError("dynamic_context_shape_mismatch")
    return context


def _recursive_batch(
    *,
    sequence: Any,
    frame: pd.DataFrame,
    probability_by_year: dict[int, torch.Tensor],
    neighbors: list[list[int]],
    feature_year: int,
) -> DAMGKBatch:
    fine_probability = probability_by_year[feature_year]
    fine_count = int(sequence.metadata["fine_node_count"])
    if fine_probability.shape != (fine_count, TWM_CLASS_COUNT):
        raise ValueError("recursive_fine_probability_shape_mismatch")
    mapping = sequence.fine_to_coarse
    aggregate = mapping / mapping.sum(dim=1, keepdim=True).clamp_min(1.0)
    all_probability = torch.cat(
        [fine_probability, aggregate @ fine_probability], dim=0
    )
    node_state = sequence.batch.node_state.clone()
    node_state[:, :TWM_CLASS_COUNT] = all_probability

    fine_context = _dynamic_fine_context(
        frame=frame,
        probability_by_year=probability_by_year,
        neighbors=neighbors,
        feature_year=feature_year,
        clock_year=feature_year,
    )
    coarse_context = aggregate @ fine_context
    coarse_context[:, 2] = 1.0
    context = torch.cat([fine_context, coarse_context], dim=0)
    return replace(
        sequence.batch,
        node_state=node_state,
        node_context=context,
        node_context_by_step=context[:, None, :],
        teacher_state_by_step=None,
    )


def _roll_region(
    *,
    model: TWMLandTransitionModel,
    frame: pd.DataFrame,
    region_edges: pd.DataFrame,
    logit_offset: float,
    cap_rate: float,
) -> tuple[Any, np.ndarray]:
    frame = frame.sort_values("node_id", kind="mergesort").reset_index(drop=True)
    sequence = _build_region_sequence(
        frame=frame,
        region_edges=region_edges,
        initial_year=2020,
        target_years=(2021,),
        future_class_by_year=None,
    )
    _, _ = _hierarchy(frame)
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
        for target_year in PREDICTION_YEARS:
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
            updated = _rate_capped_update(
                current_probability=probability_by_year[feature_year],
                change_logit=output.change_logit[:fine_count],
                destination_logits=output.destination_logits[:fine_count],
                logit_offset=logit_offset,
                cap_rate=cap_rate,
                group_sizes=[fine_count],
            )
            probability_by_year[target_year] = updated
            probabilities.append(updated)
    return sequence, torch.stack(probabilities, dim=1).cpu().numpy().astype(np.float64)


def _predict_fold(
    *,
    model: TWMLandTransitionModel,
    fold_index: int,
    fold_test: pd.DataFrame,
    edges: pd.DataFrame,
    logit_offset: float,
    cap_rate: float,
) -> pd.DataFrame:
    sequences = []
    probabilities = []
    for region_id, region_frame in fold_test.groupby("region_id", sort=True):
        sequence, probability = _roll_region(
            model=model,
            frame=region_frame,
            region_edges=edges[edges["region_id"] == region_id],
            logit_offset=logit_offset,
            cap_rate=cap_rate,
        )
        sequences.append(sequence)
        probabilities.append(probability)
    return _prediction_frame(
        fold_index=fold_index,
        sequences=sequences,
        probabilities=np.concatenate(probabilities, axis=0),
    )


def run_twm_multiregion_posthoc_v2(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    epochs: int = DEFAULT_EPOCHS,
) -> dict[str, Any]:
    if not seeds or epochs <= 0:
        raise ValueError("positive_epochs_and_at_least_one_seed_required")
    protocol_path = protocol_path.resolve()
    output_root = output_root.resolve()
    protocol = _load_json(protocol_path)
    train = pd.read_parquet(DEVELOPMENT_ROOT / "observed_train.parquet")
    inputs = pd.read_parquet(DEVELOPMENT_ROOT / "observed_inputs.parquet")
    edges = pd.read_parquet(DEVELOPMENT_ROOT / "observed_edges.parquet")
    folds = _load_json(DEVELOPMENT_ROOT / "region_folds.json")["folds"]
    output_root.mkdir(parents=True, exist_ok=True)

    frames_by_seed: dict[int, list[pd.DataFrame]] = {seed: [] for seed in seeds}
    member_reports = []
    for seed in seeds:
        fold_reports = []
        for fold in folds:
            fold_index = int(fold["fold_index"])
            fold_train = train[train["fold_index"] == fold_index]
            fold_validation = inputs[
                (inputs["fold_index"] == fold_index)
                & (inputs["split"] == "validation")
            ]
            fold_test = inputs[
                (inputs["fold_index"] == fold_index) & (inputs["split"] == "test")
            ]
            train_sequences = _annual_sequences(
                frame=fold_train, edges=edges, long_layout=True
            )
            validation_sequences = _annual_sequences(
                frame=fold_validation, edges=edges, long_layout=False
            )
            stacked_train = _stack_sequences(train_sequences)
            model = _fit_one_year_model(
                train=stacked_train, seed=seed, epochs=epochs
            )
            cap_candidates = _historical_cap_candidates(fold_train)
            selected, trials = _select_validation_configuration(
                model=model,
                validation_sequences=validation_sequences,
                cap_rates=cap_candidates,
            )

            seed_root = output_root / f"seed_{seed}"
            weights_path = seed_root / f"fold_{fold_index}_weights.pt"
            weights_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = weights_path.with_suffix(".pt.tmp")
            torch.save(model.state_dict(), temporary)
            temporary.replace(weights_path)
            trials_path = seed_root / f"fold_{fold_index}_selection_trials.json"
            trials_path.write_text(
                json.dumps(trials, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            frames_by_seed[seed].append(
                _predict_fold(
                    model=model,
                    fold_index=fold_index,
                    fold_test=fold_test,
                    edges=edges,
                    logit_offset=float(selected["logit_offset"]),
                    cap_rate=float(selected["cap_rate"]),
                )
            )
            fold_reports.append(
                {
                    "fold_index": fold_index,
                    "training_window_count": len(train_sequences),
                    "validation_window_count": len(validation_sequences),
                    "selected": selected,
                    "cap_rate_candidates": cap_candidates,
                    "weights": _artifact(weights_path),
                    "selection_trials": _artifact(trials_path),
                }
            )
            print(
                "completed TWM V2 "
                f"seed={seed} fold={fold_index} "
                f"offset={selected['logit_offset']} cap={selected['cap_rate']}",
                flush=True,
            )
        member_reports.append({"seed": seed, "folds": fold_reports})

    expected_rows = int((inputs["split"] == "test").sum()) * len(PREDICTION_YEARS)
    member_frames = []
    for member in member_reports:
        seed = int(member["seed"])
        frame = _validate_full_prediction(
            pd.concat(frames_by_seed[seed], ignore_index=True), expected_rows
        )
        path = output_root / f"seed_{seed}/prediction_2021_2025.parquet"
        _write_parquet(frame, path)
        member["prediction"] = _artifact(path)
        member["prediction"]["row_count"] = len(frame)
        member_frames.append(frame)

    reference_keys = member_frames[0][KEY_COLUMNS]
    if any(
        not frame[KEY_COLUMNS].equals(reference_keys) for frame in member_frames[1:]
    ):
        raise ValueError("twm_v2_member_prediction_keys_mismatch")
    ensemble = reference_keys.copy()
    ensemble[PROBABILITY_COLUMNS] = np.mean(
        np.stack(
            [frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64) for frame in member_frames]
        ),
        axis=0,
    )
    ensemble = _validate_full_prediction(ensemble, expected_rows)
    prediction_path = output_root / "twm_v2_prediction_2021_2025.parquet"
    _write_parquet(ensemble, prediction_path)

    v1_report = _load_json(V1_OUTPUT_ROOT / "prediction_report.json")
    report = {
        "schema": "gwm_bench.multiregion_twm_posthoc_v2_prediction.v1",
        "status": "posthoc_development_prediction_complete",
        "protocol_id": protocol["protocol_id"],
        "prediction_years": list(PREDICTION_YEARS),
        "candidate": {
            "name": "TWM V2 unified one-year recursive model",
            "seeds": list(seeds),
            "epochs": epochs,
            "training_windows": [list(window) for window in ANNUAL_WINDOWS],
            "model_selection_data": "2017-2020 validation-region annual windows only",
            "recursive_context": (
                "recompute predicted change history, neighborhood distribution, "
                "built share, entropy, and same-class share every year"
            ),
            "annual_change_control": (
                "validation-selected cap from training-period regional change-rate statistics"
            ),
            "post_2020_observed_land_or_viirs_used": False,
            "labels_2021_2025_used_for_training_or_selection": False,
        },
        "members": member_reports,
        "artifacts": {
            "prediction": {
                **_artifact(prediction_path),
                "row_count": len(ensemble),
            },
            "reference_baselines": v1_report["artifacts"]["baselines"],
        },
        "source": _artifact(Path(__file__)),
        "integrity": {
            "all_15_weights_saved": len(seeds) * len(folds) == 15,
            "selection_trials_saved": True,
            "2024_2025_labels_opened_by_predictor": False,
            "original_blind_holdout_artifacts_overwritten": False,
        },
        "claim_boundary": {
            "development_only": True,
            "blind_holdout_improvement": False,
            "reason": "2024-2025 labels were known before V2 was designed",
            "fresh_hidden_labels_required_for_unbiased_acceptance": True,
        },
    }
    report_path = output_root / "prediction_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
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
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    args = parser.parse_args()
    run_twm_multiregion_posthoc_v2(
        protocol_path=args.protocol,
        output_root=args.output_root,
        seeds=tuple(args.seeds),
        epochs=args.epochs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
