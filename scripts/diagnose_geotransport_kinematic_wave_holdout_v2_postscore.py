#!/usr/bin/env python3
"""Run post-score diagnostics without changing the frozen v2 evaluation."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SCORE_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_score.json"
)
ROLLOUT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_rollout_report.json"
)
OUTCOME_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_outcomes_report.json"
)
OUTPUT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_postscore_diagnostic.json"
)
SYSTEM_IDS = ("center_hill", "j_percy_priest")


def main() -> int:
    if OUTPUT_PATH.exists():
        raise ValueError("kinematic_holdout_v2_postscore_diagnostic_refuses_overwrite")
    score_body, score = _load_json(SCORE_PATH)
    rollout_body, rollout = _load_json(ROLLOUT_PATH)
    outcome_body, outcomes = _load_json(OUTCOME_PATH)
    systems: dict[str, Any] = {}
    for system_id in SYSTEM_IDS:
        prediction_descriptor = rollout["systems"][system_id][
            "prediction_artifact"
        ]
        outcome_descriptor = outcomes["systems"][system_id]["outcome_values"]
        predictions = _prediction_values(_read_verified(prediction_descriptor))
        observations = _outcome_values(_read_verified(outcome_descriptor))
        systems[system_id] = _diagnose(
            predictions=predictions,
            observations=observations,
            frozen_score=score["systems"][system_id],
        )
    report = {
        "schema": "gwm.geotransport.kinematic_wave_holdout_postscore_diagnostic.v1",
        "status": "posthoc_diagnostic_not_registered_evaluation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "score": _artifact(SCORE_PATH, score_body),
            "rollout": _artifact(ROLLOUT_PATH, rollout_body),
            "outcomes": _artifact(OUTCOME_PATH, outcome_body),
        },
        "systems": systems,
        "interpretation_boundary": {
            "outcomes_available_when_diagnostic_defined": True,
            "registered_prediction_metric_or_gate_changed": False,
            "lag_or_affine_result_admissible_as_model": False,
            "prediction_rerun_permitted": False,
            "operator_form_admitted": False,
        },
    }
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT_PATH)
    for system_id in SYSTEM_IDS:
        diagnostic = systems[system_id]
        print(
            f"{system_id}_zero_lag_correlation="
            f"{diagnostic['shape']['zero_lag_pearson_correlation']}"
        )
        print(
            f"{system_id}_best_prediction_time_shift_hours="
            f"{diagnostic['posthoc_lag_scan']['best_rmse_prediction_time_shift_hours']}"
        )
    return 0


def _diagnose(
    *,
    predictions: dict[datetime, tuple[float, float]],
    observations: dict[datetime, float | None],
    frozen_score: dict[str, Any],
) -> dict[str, Any]:
    times = sorted(predictions)
    common_times = [
        value
        for value in times
        if observations.get(value) is not None
        and observations.get(value - timedelta(hours=1)) is not None
    ]
    observed = np.asarray([observations[value] for value in common_times], dtype=float)
    predicted = np.asarray([predictions[value][0] for value in common_times])
    silent = np.asarray([predictions[value][1] for value in common_times])
    if len(observed) != frozen_score["scored_hour_count"]:
        raise ValueError("kinematic_holdout_v2_postscore_mask_mismatch")
    affine_slope, affine_intercept = np.polyfit(predicted, observed, 1)
    affine = affine_slope * predicted + affine_intercept
    lag_rows: list[dict[str, Any]] = []
    for shift in range(-48, 49):
        pairs = [
            (prediction[0], observations.get(timestamp + timedelta(hours=shift)))
            for timestamp, prediction in predictions.items()
            if observations.get(timestamp + timedelta(hours=shift)) is not None
        ]
        if len(pairs) < 500:
            continue
        candidate_prediction = np.asarray([value[0] for value in pairs])
        candidate_observed = np.asarray([value[1] for value in pairs], dtype=float)
        lag_rows.append(
            {
                "prediction_time_shift_hours": shift,
                "complete_pair_count": len(pairs),
                "rmse_m3s": _rmse(candidate_observed, candidate_prediction),
                "pearson_correlation": _correlation(
                    candidate_observed, candidate_prediction
                ),
            }
        )
    best_rmse = min(lag_rows, key=lambda row: row["rmse_m3s"])
    best_correlation = max(lag_rows, key=lambda row: row["pearson_correlation"])
    event_threshold = float(np.quantile(observed, 0.9))
    event = observed >= event_threshold
    branch_effect = predicted - silent
    return {
        "registered_score_unchanged": {
            "scored_hour_count": len(observed),
            "kinematic_rmse_m3s": frozen_score["metrics"]["kinematic_wave"][
                "rmse_m3s"
            ],
            "persistence_rmse_m3s": frozen_score["metrics"][
                "observed_persistence"
            ]["rmse_m3s"],
            "accuracy_gate_passed": frozen_score["gates"][
                "kinematic_beats_observed_persistence_rmse"
            ],
        },
        "distribution": {
            "observed_mean_m3s": float(observed.mean()),
            "observed_standard_deviation_m3s": float(observed.std()),
            "kinematic_mean_m3s": float(predicted.mean()),
            "kinematic_standard_deviation_m3s": float(predicted.std()),
            "branch_silent_mean_m3s": float(silent.mean()),
            "mean_branch_effect_m3s": float(branch_effect.mean()),
            "maximum_absolute_branch_effect_m3s": float(
                np.max(np.abs(branch_effect))
            ),
        },
        "shape": {
            "zero_lag_pearson_correlation": _correlation(observed, predicted),
            "first_difference_pearson_correlation": _correlation(
                np.diff(observed), np.diff(predicted)
            ),
            "standard_deviation_ratio_prediction_to_observed": float(
                predicted.std() / observed.std()
            ),
        },
        "top_observed_decile": {
            "threshold_m3s": event_threshold,
            "hour_count": int(event.sum()),
            "kinematic_rmse_m3s": _rmse(observed[event], predicted[event]),
            "kinematic_bias_m3s": float((predicted[event] - observed[event]).mean()),
        },
        "posthoc_lag_scan": {
            "range_hours": [-48, 48],
            "prediction_time_shift_definition": (
                "positive moves a prediction to a later observation timestamp"
            ),
            "best_rmse_prediction_time_shift_hours": best_rmse[
                "prediction_time_shift_hours"
            ],
            "best_rmse_m3s": best_rmse["rmse_m3s"],
            "best_correlation_prediction_time_shift_hours": best_correlation[
                "prediction_time_shift_hours"
            ],
            "best_pearson_correlation": best_correlation["pearson_correlation"],
            "registered_gate_use": False,
        },
        "posthoc_affine_oracle": {
            "slope": float(affine_slope),
            "intercept_m3s": float(affine_intercept),
            "rmse_m3s": _rmse(observed, affine),
            "outcome_fitted": True,
            "admissible_prediction": False,
        },
    }


def _prediction_values(body: bytes) -> dict[datetime, tuple[float, float]]:
    result: dict[datetime, tuple[float, float]] = {}
    for row in csv.DictReader(body.decode("utf-8").splitlines()):
        result[_parse_utc(row["support_end_utc"])] = (
            float(row["kinematic_wave_m3s"]),
            float(row["branch_silent_negative_control_m3s"]),
        )
    return result


def _outcome_values(body: bytes) -> dict[datetime, float | None]:
    result: dict[datetime, float | None] = {}
    for row in csv.DictReader(body.decode("utf-8").splitlines()):
        result[_parse_utc(row["support_end_utc"])] = (
            None
            if row["observed_discharge_m3s"] == ""
            else float(row["observed_discharge_m3s"])
        )
    return result


def _correlation(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.corrcoef(first, second)[0, 1])


def _rmse(observed: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((predicted - observed) ** 2)))


def _read_verified(descriptor: dict[str, Any]) -> bytes:
    path = REPO_ROOT / descriptor["path"]
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor["sha256"]
        or len(body) != descriptor["size_bytes"]
    ):
        raise ValueError("kinematic_holdout_v2_postscore_artifact_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


if __name__ == "__main__":
    raise SystemExit(main())
