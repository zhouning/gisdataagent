#!/usr/bin/env python3
"""Run all frozen V4 model and control predictions without target access."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import resource
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
import torch

from v4_weekly_models import (
    ACTION_COLUMNS,
    STATE_COLUMNS,
    control_inputs,
    fit_ridge_models,
    load_development,
    load_relations,
    load_test_input,
    prediction_frame,
    predict_graph_recursive,
    predict_ridge_recursive,
    save_checkpoint,
    seasonal_prediction,
    select_config,
    sha256_file,
    train_graph_model,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
BUNDLE_ROOT = DRAFT_ROOT / "rc1_bundle"
PREDICTION_ROOT = DRAFT_ROOT / "predictions"
SEAL_PATH = DRAFT_ROOT / "runtime_r3_evaluator_seal.json"
DEVELOPMENT_PATH = BUNDLE_ROOT / "development/weekly_state_action.parquet"
TRAINING_MANIFEST_PATH = BUNDLE_ROOT / "development/training_row_manifest.json"
HISTORY_PATH = BUNDLE_ROOT / "test_input/weekly_state_history.parquet"
ACTION_PATH = BUNDLE_ROOT / "test_input/future_action_spec.parquet"
KEY_PATH = BUNDLE_ROOT / "test_input/submission_keys.parquet"
ZONE_PATH = BUNDLE_ROOT / "graph/zone_metadata.parquet"
GRAPH_PATH = BUNDLE_ROOT / "graph/spatial_edges.parquet"
RUNTIME_CONTRACT_PATH = DRAFT_ROOT / "runtime_r3_contract.json"
SUBMISSION_CONTRACT_PATH = DRAFT_ROOT / "submission_contract.json"
SEEDS = (31, 47, 73)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def environment_payload() -> dict[str, Any]:
    return {
        "schema": "gwm_bench.foundation_v4_runtime_environment.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit_learn": sklearn.__version__,
        "torch": torch.__version__,
        "torch_threads": torch.get_num_threads(),
        "pid": os.getpid(),
    }


def write_prediction_bundle(
    model_id: str,
    frame: pd.DataFrame,
    *,
    model_spec: dict[str, Any],
    run_report: dict[str, Any],
) -> dict[str, Any]:
    root = PREDICTION_ROOT / model_id
    root.mkdir(parents=True, exist_ok=True)
    prediction_path = root / "prediction.parquet"
    model_spec_path = root / "model_spec.json"
    training_manifest_path = root / "training_row_manifest.json"
    runtime_environment_path = root / "runtime_environment.json"
    run_report_path = root / "run_report.json"
    frame.to_parquet(prediction_path, index=False)
    write_json(model_spec_path, model_spec)
    write_json(
        training_manifest_path,
        {
            "schema": "gwm_bench.foundation_v4_submission_training_reference.v1",
            "source": artifact(TRAINING_MANIFEST_PATH),
            "post_2025_action_rows": 0,
            "model_process_target_access_permitted": False,
        },
    )
    write_json(runtime_environment_path, environment_payload())
    run_report["prediction"] = artifact(prediction_path)
    run_report["model_spec"] = artifact(model_spec_path)
    run_report["training_manifest"] = artifact(training_manifest_path)
    run_report["runtime_environment"] = artifact(runtime_environment_path)
    write_json(run_report_path, run_report)
    return {
        "prediction_path": str(prediction_path.relative_to(REPO_ROOT)),
        "prediction_sha256": sha256_file(prediction_path),
        "model_spec_path": str(model_spec_path.relative_to(REPO_ROOT)),
        "run_report_path": str(run_report_path.relative_to(REPO_ROOT)),
    }


def ensemble_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    key_columns = ["zone_id", "horizon_week"]
    prediction_columns = [f"{target}_prediction" for target in STATE_COLUMNS]
    base = frames[0][key_columns].copy()
    for column in prediction_columns:
        base[column] = np.mean(
            [frame[column].to_numpy(dtype=np.float64) for frame in frames], axis=0
        )
    return base


def member_report(
    model_id: str,
    seed: int,
    checkpoint_path: Path,
    prediction_path: Path,
    training: dict[str, Any],
    started: float,
) -> None:
    report = {
        "schema": "gwm_bench.foundation_v4_seed_run.v1",
        "model_id": model_id,
        "seed": seed,
        "started_at_monotonic": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": time.monotonic() - started,
        "ru_maxrss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "exit_status": "success",
        "failure_state": None,
        "checkpoint": artifact(checkpoint_path),
        "prediction": artifact(prediction_path),
        "training_final_loss": training["history"][-1]["weighted_smooth_l1"],
    }
    write_json(prediction_path.with_name("run_report.json"), report)


def main() -> int:
    seal = load_json(SEAL_PATH)
    if seal["status"] != "RUNTIME_R3_EVALUATOR_SEALED_PREDICTIONS_PENDING":
        raise ValueError("Runtime-R3 and evaluator are not sealed")
    runtime_contract = load_json(RUNTIME_CONTRACT_PATH)
    if runtime_contract["read_routes"]["model_runtime_denied"] != [
        "rc1_bundle/test_targets"
    ]:
        raise ValueError("unexpected runtime target-denial contract")

    started_all = time.monotonic()
    events = load_development(DEVELOPMENT_PATH)
    test = load_test_input(HISTORY_PATH, ACTION_PATH)
    relations, graph_audit = load_relations(GRAPH_PATH)
    zone_metadata = pd.read_parquet(ZONE_PATH)
    expected_keys = pd.read_parquet(KEY_PATH).sort_values(
        ["zone_id", "horizon_week"]
    ).reset_index(drop=True)
    selected_config, selection_report = select_config(events, relations, seed=31)
    selection_report.update(
        {
            "schema": "gwm_bench.foundation_v4_weekly_loo_selection.v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "test_target_rows_loaded": False,
            "inputs": {
                "development": artifact(DEVELOPMENT_PATH),
                "graph": artifact(GRAPH_PATH),
                "code": artifact(Path(__file__).with_name("v4_weekly_models.py")),
            },
        }
    )
    selection_path = PREDICTION_ROOT / "development_selection.json"
    write_json(selection_path, selection_report)

    prediction_members: dict[str, list[pd.DataFrame]] = {
        "uwm_dam_gk_action": [],
        "dam_gk_no_action": [],
    }
    action_models = []
    no_action_models = []
    training_reports: dict[str, list[dict[str, Any]]] = {
        "uwm_dam_gk_action": [],
        "dam_gk_no_action": [],
    }
    correct_future, correct_history, correct_relations, _ = control_inputs(
        "correct_action", test, relations, zone_metadata
    )
    zero_future, zero_history, _, _ = control_inputs(
        "action_deleted", test, relations, zone_metadata
    )
    for seed in SEEDS:
        for model_id, action_mode, future, history, relation_values in (
            (
                "uwm_dam_gk_action",
                "compositional",
                correct_future,
                correct_history,
                correct_relations,
            ),
            (
                "dam_gk_no_action",
                "no_action",
                zero_future,
                zero_history,
                relations,
            ),
        ):
            started = time.monotonic()
            model, scalers, training = train_graph_model(
                list(events.values()), relations, selected_config, seed, action_mode
            )
            prediction = predict_graph_recursive(
                model,
                scalers,
                test,
                relation_values,
                action_future=future,
                action_history=history,
            )
            frame = prediction_frame(prediction)
            member_root = PREDICTION_ROOT / model_id / "members" / f"seed_{seed}"
            member_root.mkdir(parents=True, exist_ok=True)
            checkpoint_path = member_root / "model.pt"
            prediction_path = member_root / "prediction.parquet"
            save_checkpoint(checkpoint_path, model, scalers, training)
            frame.to_parquet(prediction_path, index=False)
            member_report(
                model_id, seed, checkpoint_path, prediction_path, training, started
            )
            prediction_members[model_id].append(frame)
            training_reports[model_id].append(training)
            if model_id == "uwm_dam_gk_action":
                action_models.append((model, scalers, seed))
            else:
                no_action_models.append((model, scalers, seed))

    submissions: dict[str, Any] = {}
    for model_id in ("uwm_dam_gk_action", "dam_gk_no_action"):
        ensemble = ensemble_frames(prediction_members[model_id])
        submissions[model_id] = write_prediction_bundle(
            model_id,
            ensemble,
            model_spec={
                "schema": "gwm_bench.foundation_v4_model_spec.v1",
                "model_id": model_id,
                "algorithm": "action-modulated multi-relation Graph-GRU"
                if model_id == "uwm_dam_gk_action"
                else "matched multi-relation Graph-GRU trained without action input",
                "selected_config": selection_report["selected_config"],
                "selection_report": artifact(selection_path),
                "seeds": list(SEEDS),
                "ensemble_rule": "arithmetic mean in raw count space",
                "graph": graph_audit,
                "action_columns": list(ACTION_COLUMNS),
                "test_target_rows_loaded": False,
            },
            run_report={
                "schema": "gwm_bench.foundation_v4_run_report.v1",
                "model_id": model_id,
                "adapter_id": "runtime_r3_weekly_graph_gru",
                "seeds": list(SEEDS),
                "member_count": 3,
                "wall_seconds_total_so_far": time.monotonic() - started_all,
                "ru_maxrss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "exit_status": "success",
                "failure_state": None,
                "test_target_rows_loaded": False,
            },
        )

    controls = [
        "action_deleted",
        "effective_date_minus_4w",
        "effective_date_plus_4w",
        "action_component_permutation",
        "cbd_scope_rewire",
        "zone_exposure_shuffle_seed_20260723",
    ]
    for control_id in controls:
        future, history, relation_values, control_audit = control_inputs(
            control_id, test, relations, zone_metadata
        )
        frames = []
        for model, scalers, seed in action_models:
            prediction = predict_graph_recursive(
                model,
                scalers,
                test,
                relation_values,
                action_future=future,
                action_history=history,
            )
            frame = prediction_frame(prediction)
            member_root = PREDICTION_ROOT / control_id / "members" / f"seed_{seed}"
            member_root.mkdir(parents=True, exist_ok=True)
            member_path = member_root / "prediction.parquet"
            frame.to_parquet(member_path, index=False)
            write_json(
                member_root / "run_report.json",
                {
                    "schema": "gwm_bench.foundation_v4_control_seed_run.v1",
                    "control_id": control_id,
                    "seed": seed,
                    "source_model": "uwm_dam_gk_action",
                    "prediction": artifact(member_path),
                    "test_target_rows_loaded": False,
                    "exit_status": "success",
                },
            )
            frames.append(frame)
        submissions[control_id] = write_prediction_bundle(
            control_id,
            ensemble_frames(frames),
            model_spec={
                "schema": "gwm_bench.foundation_v4_control_spec.v1",
                "model_id": control_id,
                "source_model": "uwm_dam_gk_action",
                "control_audit": control_audit,
                "seeds": list(SEEDS),
                "test_target_rows_loaded": False,
            },
            run_report={
                "schema": "gwm_bench.foundation_v4_run_report.v1",
                "model_id": control_id,
                "adapter_id": "runtime_r3_action_control",
                "seeds": list(SEEDS),
                "exit_status": "success",
                "failure_state": None,
                "test_target_rows_loaded": False,
            },
        )

    for model_id, spatial in (
        ("fixed_adjacency_spatial_ar", True),
        ("nonspatial_historical_ar", False),
    ):
        started = time.monotonic()
        ridge_models = fit_ridge_models(events, relations, spatial=spatial)
        prediction = predict_ridge_recursive(
            ridge_models, test, relations, spatial=spatial
        )
        submissions[model_id] = write_prediction_bundle(
            model_id,
            prediction_frame(prediction),
            model_spec={
                "schema": "gwm_bench.foundation_v4_model_spec.v1",
                "model_id": model_id,
                "algorithm": "per-zone multi-output Ridge autoregression",
                "lags": [1, 2, 4, 8],
                "alpha": 5.0,
                "uses_geographic_adjacency_message": spatial,
                "uses_action": False,
                "test_target_rows_loaded": False,
            },
            run_report={
                "schema": "gwm_bench.foundation_v4_run_report.v1",
                "model_id": model_id,
                "adapter_id": "runtime_r3_ridge",
                "seed": None,
                "wall_seconds": time.monotonic() - started,
                "ru_maxrss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "exit_status": "success",
                "failure_state": None,
                "test_target_rows_loaded": False,
            },
        )

    submissions["seasonal_persistence_52w"] = write_prediction_bundle(
        "seasonal_persistence_52w",
        prediction_frame(seasonal_prediction(test)),
        model_spec={
            "schema": "gwm_bench.foundation_v4_model_spec.v1",
            "model_id": "seasonal_persistence_52w",
            "algorithm": "copy the action-aligned week from exactly 52 weeks earlier",
            "uses_action": False,
            "test_target_rows_loaded": False,
        },
        run_report={
            "schema": "gwm_bench.foundation_v4_run_report.v1",
            "model_id": "seasonal_persistence_52w",
            "adapter_id": "runtime_r3_seasonal_persistence",
            "seed": None,
            "exit_status": "success",
            "failure_state": None,
            "test_target_rows_loaded": False,
        },
    )

    prediction_columns = [f"{target}_prediction" for target in STATE_COLUMNS]
    for model_id, entry in submissions.items():
        frame = pd.read_parquet(REPO_ROOT / entry["prediction_path"])
        actual_keys = frame[["zone_id", "horizon_week"]].sort_values(
            ["zone_id", "horizon_week"]
        ).reset_index(drop=True)
        if not np.array_equal(
            actual_keys.to_numpy(dtype=np.int64),
            expected_keys.to_numpy(dtype=np.int64),
        ):
            raise ValueError(f"submission key mismatch: {model_id}")
        values = frame[prediction_columns].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError(f"invalid prediction values: {model_id}")

    manifest = {
        "schema": "gwm_bench.foundation_v4_prediction_manifest_draft.v1",
        "suite_id": seal["suite_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ALL_REQUIRED_PREDICTIONS_MATERIALIZED_UNCOMMITTED",
        "test_target_rows_loaded": False,
        "runtime_seal": artifact(SEAL_PATH),
        "runtime_contract": artifact(RUNTIME_CONTRACT_PATH),
        "submission_contract": artifact(SUBMISSION_CONTRACT_PATH),
        "selection": artifact(selection_path),
        "required_models": seal["required_model_ids"],
        "required_controls": seal["required_control_ids"],
        "submissions": submissions,
        "wall_seconds": time.monotonic() - started_all,
        "ru_maxrss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    manifest_path = PREDICTION_ROOT / "prediction_manifest_draft.json"
    write_json(manifest_path, manifest)
    print("GWM-Bench Foundation V4.0: ALL_REQUIRED_PREDICTIONS_MATERIALIZED_UNCOMMITTED")
    print(f"Prediction manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
