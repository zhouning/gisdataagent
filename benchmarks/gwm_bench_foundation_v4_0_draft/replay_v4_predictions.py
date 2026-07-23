#!/usr/bin/env python3
"""Replay every V4 prediction from frozen inputs and model checkpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v4_weekly_models import (
    STATE_COLUMNS,
    control_inputs,
    fit_ridge_models,
    load_checkpoint,
    load_development,
    load_relations,
    load_test_input,
    prediction_frame,
    predict_graph_recursive,
    predict_ridge_recursive,
    seasonal_prediction,
    sha256_file,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
BUNDLE_ROOT = DRAFT_ROOT / "rc1_bundle"
PREDICTION_ROOT = DRAFT_ROOT / "predictions"
MANIFEST_PATH = PREDICTION_ROOT / "prediction_manifest_draft.json"
OUTPUT_PATH = PREDICTION_ROOT / "runtime_replay_report.json"
SEEDS = (31, 47, 73)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def compare_frames(expected: pd.DataFrame, actual: pd.DataFrame) -> dict[str, Any]:
    keys = ["zone_id", "horizon_week"]
    columns = [f"{target}_prediction" for target in STATE_COLUMNS]
    expected = expected.sort_values(keys).reset_index(drop=True)
    actual = actual.sort_values(keys).reset_index(drop=True)
    key_match = np.array_equal(
        expected[keys].to_numpy(dtype=np.int64),
        actual[keys].to_numpy(dtype=np.int64),
    )
    difference = np.abs(
        expected[columns].to_numpy(dtype=np.float64)
        - actual[columns].to_numpy(dtype=np.float64)
    )
    maximum = float(difference.max())
    return {
        "key_match": key_match,
        "max_abs_difference": maximum,
        "pass": bool(key_match and maximum <= 1e-6),
    }


def ensemble(frames: list[pd.DataFrame]) -> pd.DataFrame:
    keys = ["zone_id", "horizon_week"]
    columns = [f"{target}_prediction" for target in STATE_COLUMNS]
    result = frames[0][keys].copy()
    for column in columns:
        result[column] = np.mean(
            [frame[column].to_numpy(dtype=np.float64) for frame in frames], axis=0
        )
    return result


def main() -> int:
    manifest = load_json(MANIFEST_PATH)
    if manifest["test_target_rows_loaded"] is not False:
        raise ValueError("prediction manifest does not preserve target firewall")
    events = load_development(BUNDLE_ROOT / "development/weekly_state_action.parquet")
    test = load_test_input(
        BUNDLE_ROOT / "test_input/weekly_state_history.parquet",
        BUNDLE_ROOT / "test_input/future_action_spec.parquet",
    )
    relations, _ = load_relations(BUNDLE_ROOT / "graph/spatial_edges.parquet")
    zone_metadata = pd.read_parquet(BUNDLE_ROOT / "graph/zone_metadata.parquet")
    checks: dict[str, Any] = {}
    loaded_action_models = []

    for model_id, control_id in (
        ("uwm_dam_gk_action", "correct_action"),
        ("dam_gk_no_action", "action_deleted"),
    ):
        future, history, relation_values, _ = control_inputs(
            control_id, test, relations, zone_metadata
        )
        replay_members = []
        for seed in SEEDS:
            root = PREDICTION_ROOT / model_id / "members" / f"seed_{seed}"
            model, scalers, _ = load_checkpoint(root / "model.pt")
            prediction = prediction_frame(
                predict_graph_recursive(
                    model,
                    scalers,
                    test,
                    relation_values,
                    action_future=future,
                    action_history=history,
                )
            )
            expected = pd.read_parquet(root / "prediction.parquet")
            checks[f"{model_id}_seed_{seed}"] = compare_frames(expected, prediction)
            replay_members.append(prediction)
            if model_id == "uwm_dam_gk_action":
                loaded_action_models.append((model, scalers, seed))
        expected_ensemble = pd.read_parquet(PREDICTION_ROOT / model_id / "prediction.parquet")
        checks[f"{model_id}_ensemble"] = compare_frames(
            expected_ensemble, ensemble(replay_members)
        )

    for control_id in (
        "action_deleted",
        "effective_date_minus_4w",
        "effective_date_plus_4w",
        "action_component_permutation",
        "cbd_scope_rewire",
        "zone_exposure_shuffle_seed_20260723",
    ):
        future, history, relation_values, _ = control_inputs(
            control_id, test, relations, zone_metadata
        )
        replay_members = []
        for model, scalers, seed in loaded_action_models:
            prediction = prediction_frame(
                predict_graph_recursive(
                    model,
                    scalers,
                    test,
                    relation_values,
                    action_future=future,
                    action_history=history,
                )
            )
            expected = pd.read_parquet(
                PREDICTION_ROOT / control_id / "members" / f"seed_{seed}" / "prediction.parquet"
            )
            checks[f"{control_id}_seed_{seed}"] = compare_frames(expected, prediction)
            replay_members.append(prediction)
        expected_ensemble = pd.read_parquet(PREDICTION_ROOT / control_id / "prediction.parquet")
        checks[f"{control_id}_ensemble"] = compare_frames(
            expected_ensemble, ensemble(replay_members)
        )

    for model_id, spatial in (
        ("fixed_adjacency_spatial_ar", True),
        ("nonspatial_historical_ar", False),
    ):
        models = fit_ridge_models(events, relations, spatial=spatial)
        prediction = prediction_frame(
            predict_ridge_recursive(models, test, relations, spatial=spatial)
        )
        expected = pd.read_parquet(PREDICTION_ROOT / model_id / "prediction.parquet")
        checks[model_id] = compare_frames(expected, prediction)

    checks["seasonal_persistence_52w"] = compare_frames(
        pd.read_parquet(PREDICTION_ROOT / "seasonal_persistence_52w/prediction.parquet"),
        prediction_frame(seasonal_prediction(test)),
    )
    passed = all(row["pass"] for row in checks.values())
    report = {
        "schema": "gwm_bench.foundation_v4_runtime_replay.v1",
        "suite_id": manifest["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_RUNTIME_R3_ALL_PREDICTIONS_REPLAYED" if passed else "FAIL",
        "test_target_rows_loaded": False,
        "prediction_manifest_sha256": sha256_file(MANIFEST_PATH),
        "check_count": len(checks),
        "checks": checks,
        "maximum_observed_absolute_difference": max(
            row["max_abs_difference"] for row in checks.values()
        ),
        "next_permitted_action": (
            "Commit all prediction and sidecar hashes before evaluator target access."
            if passed
            else "Fix replay failures without evaluator target access."
        ),
    }
    write_json(OUTPUT_PATH, report)
    print(f"GWM-Bench Foundation V4.0 replay: {report['status']}")
    print(f"Replay report: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
