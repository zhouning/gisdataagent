#!/usr/bin/env python3
"""Replay and validate every V5 Runtime-R4 prediction before commitment."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from action_transfer_evaluator import validate_submission
from v5_runtime_models import (
    STATE_COLUMNS,
    action_control_inputs,
    fit_ridge_models,
    load_checkpoint,
    load_development,
    load_relations,
    load_test_input,
    prediction_frame,
    predict_residual,
    predict_ridge_recursive,
    sha256_file,
    test_residual_example,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PREDICTION_ROOT = DRAFT_ROOT / "predictions"
DRAFT_MANIFEST_PATH = PREDICTION_ROOT / "prediction_manifest_draft.json"
RUNTIME_PATH = DRAFT_ROOT / "runtime_r4_contract.json"
CONTRACT_PATH = DRAFT_ROOT / "submission_contract.json"
SEAL_PATH = DRAFT_ROOT / "runtime_r4_evaluator_seal.json"
OUTPUT_PATH = PREDICTION_ROOT / "runtime_replay_report.json"
KEY_COLUMNS = ["fold_id", "zone_id", "horizon_week"]
PREDICTION_COLUMNS = [f"{target}_prediction" for target in STATE_COLUMNS]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
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


def artifact_ok(row: dict[str, Any]) -> bool:
    path = REPO_ROOT / row["path"]
    return (
        path.is_file()
        and path.stat().st_size == row["bytes"]
        and sha256_file(path) == row["sha256"]
    )


def assert_allowed(path: Path) -> None:
    if "test_targets" in path.resolve().parts:
        raise PermissionError(f"replay process denied answer path: {path}")


def canonical(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["fold_id"] = result["fold_id"].astype(str)
    result["zone_id"] = result["zone_id"].astype(np.int64)
    result["horizon_week"] = result["horizon_week"].astype(np.int64)
    return result.sort_values(KEY_COLUMNS).reset_index(drop=True)


def max_abs_difference(left: pd.DataFrame, right: pd.DataFrame) -> float:
    left = canonical(left)
    right = canonical(right)
    if not left[KEY_COLUMNS].equals(right[KEY_COLUMNS]):
        return float("inf")
    return float(
        np.max(
            np.abs(
                left[PREDICTION_COLUMNS].to_numpy(dtype=np.float64)
                - right[PREDICTION_COLUMNS].to_numpy(dtype=np.float64)
            )
        )
    )


def fold_paths(fold: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Path]:
    root = REPO_ROOT / fold["fold_root"]
    firewall = runtime["contracts"]["OuterFoldFirewall"]
    return {
        "development": root / firewall["development_relative_path"],
        "history": root / firewall["history_relative_path"],
        "action": root / firewall["action_relative_path"],
        "keys": root / firewall["submission_keys_relative_path"],
        "graph": root / firewall["test_graph_relative_path"],
        "zone_metadata": root / "graph/zone_metadata.parquet",
    }


def fold_prediction_path(model_id: str, fold_id: str, seed: int | None) -> Path:
    if seed is None:
        return PREDICTION_ROOT / model_id / "folds" / fold_id / "prediction.parquet"
    return (
        PREDICTION_ROOT
        / model_id
        / "members"
        / f"seed_{seed}"
        / "folds"
        / fold_id
        / "prediction.parquet"
    )


def main() -> int:
    runtime = load_json(RUNTIME_PATH)
    contract = load_json(CONTRACT_PATH)
    seal = load_json(SEAL_PATH)
    manifest = load_json(DRAFT_MANIFEST_PATH)
    if manifest["status"] != "ALL_REQUIRED_MULTIFOLD_PREDICTIONS_MATERIALIZED_UNCOMMITTED":
        raise ValueError("prediction draft is not ready for replay")
    if manifest["test_target_rows_loaded"] is not False:
        raise ValueError("prediction draft reports target access")
    required_ids = [*runtime["required_models"], *runtime["required_controls"]]
    seeds = tuple(runtime["stochastic_seed_contract"]["required_seeds"])
    checks: dict[str, bool] = {}
    aggregate_artifact_checks: dict[str, bool] = {}
    sidecar_checks: dict[str, bool] = {}
    replay_differences: dict[str, float] = {}
    ensemble_differences: dict[str, float] = {}
    changed_fold_counts: dict[str, int] = {control_id: 0 for control_id in runtime["required_controls"]}

    checks["runtime_seal_is_predictions_pending"] = seal["status"] == (
        "RUNTIME_R4_EVALUATOR_SEALED_PREDICTIONS_PENDING"
    )
    checks["manifest_ids_exactly_match_runtime"] = set(manifest["submissions"]) == set(
        required_ids
    )
    checks["runner_and_model_core_artifacts_match"] = artifact_ok(manifest["runner"]) and artifact_ok(
        manifest["model_core"]
    )

    expected_keys_parts = []
    for fold in runtime["outer_folds"]:
        paths = fold_paths(fold, runtime)
        for path in paths.values():
            assert_allowed(path)
        keys = pd.read_parquet(paths["keys"])
        keys.insert(0, "fold_id", fold["fold_id"])
        expected_keys_parts.append(keys)
    expected_keys = pd.concat(expected_keys_parts, ignore_index=True)

    aggregate_frames: dict[str, pd.DataFrame] = {}
    for model_id in required_ids:
        entry = manifest["submissions"][model_id]
        aggregate_artifact_checks[model_id] = artifact_ok(entry["prediction_artifact"])
        sidecar_checks[model_id] = all(
            artifact_ok(entry[name])
            for name in (
                "model_spec",
                "nested_selection_receipts",
                "fold_training_manifests",
                "runtime_environment",
                "run_report",
            )
        )
        aggregate_frames[model_id] = validate_submission(
            pd.read_parquet(REPO_ROOT / entry["prediction_artifact"]["path"]),
            expected_keys,
            contract,
        )
    checks["all_aggregate_prediction_artifacts_match"] = all(
        aggregate_artifact_checks.values()
    )
    checks["all_required_sidecars_match"] = all(sidecar_checks.values())
    checks["all_eleven_aggregate_submissions_validate"] = len(aggregate_frames) == 11

    for model_id in runtime["deterministic_submission_ids"]:
        fold_frames = [
            pd.read_parquet(fold_prediction_path(model_id, fold["fold_id"], None))
            for fold in runtime["outer_folds"]
        ]
        combined = pd.concat(fold_frames, ignore_index=True)
        ensemble_differences[f"{model_id}/fold_concat"] = max_abs_difference(
            combined, aggregate_frames[model_id]
        )

    seed_member_count = 0
    for model_id in runtime["stochastic_submission_ids"]:
        member_frames = []
        for seed in seeds:
            path = PREDICTION_ROOT / model_id / "members" / f"seed_{seed}" / "prediction.parquet"
            member = validate_submission(pd.read_parquet(path), expected_keys, contract)
            fold_concat = pd.concat(
                [
                    pd.read_parquet(
                        fold_prediction_path(model_id, fold["fold_id"], seed)
                    )
                    for fold in runtime["outer_folds"]
                ],
                ignore_index=True,
            )
            ensemble_differences[f"{model_id}/seed_{seed}/fold_concat"] = max_abs_difference(
                fold_concat, member
            )
            member_frames.append(canonical(member))
            seed_member_count += 1
        mean_frame = member_frames[0][KEY_COLUMNS].copy()
        for column in PREDICTION_COLUMNS:
            mean_frame[column] = np.mean(
                [frame[column].to_numpy(dtype=np.float64) for frame in member_frames],
                axis=0,
            )
        ensemble_differences[f"{model_id}/seed_mean"] = max_abs_difference(
            mean_frame, aggregate_frames[model_id]
        )
    checks["exactly_27_seed_level_multifold_predictions_validate"] = seed_member_count == 27
    checks["all_fold_concats_and_seed_ensembles_match"] = all(
        value <= 1e-10 for value in ensemble_differences.values()
    )

    for fold in runtime["outer_folds"]:
        fold_id = fold["fold_id"]
        paths = fold_paths(fold, runtime)
        events = load_development(paths["development"], fold["training_events"])
        test = load_test_input(paths["history"], paths["action"])
        relations, _ = load_relations(paths["graph"])
        zone_metadata = pd.read_parquet(paths["zone_metadata"])
        adjacency = relations[0]
        expected_history = pd.read_parquet(
            fold_prediction_path("history_ar_backbone", fold_id, None)
        )
        expected_spatial = pd.read_parquet(
            fold_prediction_path("fixed_adjacency_spatial_ar", fold_id, None)
        )
        history_models = fit_ridge_models(events, adjacency, spatial=False, alpha=5.0)
        replay_history = prediction_frame(
            fold_id,
            predict_ridge_recursive(history_models, test, adjacency, spatial=False),
        )
        spatial_models = fit_ridge_models(events, adjacency, spatial=True, alpha=5.0)
        replay_spatial = prediction_frame(
            fold_id,
            predict_ridge_recursive(spatial_models, test, adjacency, spatial=True),
        )
        replay_differences[f"history_ar_backbone/{fold_id}"] = max_abs_difference(
            replay_history, expected_history
        )
        replay_differences[f"fixed_adjacency_spatial_ar/{fold_id}"] = max_abs_difference(
            replay_spatial, expected_spatial
        )
        history_array = expected_history.sort_values(
            ["horizon_week", "zone_id"]
        )[PREDICTION_COLUMNS].to_numpy(dtype=np.float32).reshape(12, 263, 4)
        example = test_residual_example(
            fold["test_event"], test, history_array, relations
        )
        swap_source = sorted(events)[0]
        swap_action = events[swap_source].action[52:].copy()

        for seed in seeds:
            candidate_checkpoint = (
                PREDICTION_ROOT
                / "uwm_dam_gk_action_residual"
                / "members"
                / f"seed_{seed}"
                / "folds"
                / fold_id
                / "model.pt"
            )
            candidate_model, candidate_scaler, _ = load_checkpoint(candidate_checkpoint)
            replay_candidate, _ = predict_residual(
                candidate_model,
                candidate_scaler,
                example,
                action_conditioned=True,
            )
            replay_candidate_frame = prediction_frame(fold_id, replay_candidate)
            expected_candidate = pd.read_parquet(
                fold_prediction_path(
                    "uwm_dam_gk_action_residual", fold_id, seed
                )
            )
            replay_differences[
                f"uwm_dam_gk_action_residual/{fold_id}/seed_{seed}"
            ] = max_abs_difference(replay_candidate_frame, expected_candidate)

            no_action_checkpoint = (
                PREDICTION_ROOT
                / "dam_gk_residual_no_action"
                / "members"
                / f"seed_{seed}"
                / "folds"
                / fold_id
                / "model.pt"
            )
            no_action_model, no_action_scaler, _ = load_checkpoint(no_action_checkpoint)
            replay_no_action, _ = predict_residual(
                no_action_model,
                no_action_scaler,
                example,
                action_conditioned=False,
            )
            replay_no_action_frame = prediction_frame(fold_id, replay_no_action)
            expected_no_action = pd.read_parquet(
                fold_prediction_path("dam_gk_residual_no_action", fold_id, seed)
            )
            replay_differences[
                f"dam_gk_residual_no_action/{fold_id}/seed_{seed}"
            ] = max_abs_difference(replay_no_action_frame, expected_no_action)

            for control_id in runtime["required_controls"]:
                future, age, control_relations, _ = action_control_inputs(
                    control_id,
                    example,
                    zone_metadata,
                    swap_action=swap_action,
                )
                replay_control, _ = predict_residual(
                    candidate_model,
                    candidate_scaler,
                    example,
                    relations=control_relations,
                    action_future=future,
                    action_age=age,
                    action_conditioned=True,
                )
                replay_control_frame = prediction_frame(fold_id, replay_control)
                expected_control = pd.read_parquet(
                    fold_prediction_path(control_id, fold_id, seed)
                )
                replay_differences[
                    f"{control_id}/{fold_id}/seed_{seed}"
                ] = max_abs_difference(replay_control_frame, expected_control)

        candidate_fold = aggregate_frames["uwm_dam_gk_action_residual"].loc[
            aggregate_frames["uwm_dam_gk_action_residual"]["fold_id"].eq(fold_id)
        ]
        for control_id in runtime["required_controls"]:
            control_fold = aggregate_frames[control_id].loc[
                aggregate_frames[control_id]["fold_id"].eq(fold_id)
            ]
            if max_abs_difference(candidate_fold, control_fold) > 1e-9:
                changed_fold_counts[control_id] += 1

    checks["all_116_fold_predictions_replay_within_tolerance"] = len(
        replay_differences
    ) == 116 and all(value <= 1e-6 for value in replay_differences.values())
    checks["action_deleted_is_exact_backbone_in_all_folds"] = max_abs_difference(
        aggregate_frames["action_deleted"], aggregate_frames["history_ar_backbone"]
    ) <= 1e-10
    checks["every_control_changes_at_least_three_of_four_fold_predictions"] = all(
        count >= 3 for count in changed_fold_counts.values()
    )
    checks["no_answer_path_was_opened_by_replay"] = True
    checks = {key: bool(value) for key, value in checks.items()}
    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.foundation_v5_runtime_r4_replay.v1",
        "suite_id": manifest["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_RUNTIME_R4_REPLAY_ALL_PREDICTIONS" if passed else "FAIL",
        "check_count": len(checks),
        "passed_check_count": sum(checks.values()),
        "failed_checks": [key for key, value in checks.items() if not value],
        "checks": checks,
        "aggregate_artifact_checks": aggregate_artifact_checks,
        "sidecar_checks": sidecar_checks,
        "changed_fold_counts_by_control": changed_fold_counts,
        "max_replay_abs_difference": max(replay_differences.values()),
        "max_ensemble_abs_difference": max(ensemble_differences.values()),
        "replay_differences": replay_differences,
        "ensemble_differences": ensemble_differences,
        "test_target_rows_loaded": False,
        "prediction_manifest_draft": artifact(DRAFT_MANIFEST_PATH),
        "runner": manifest["runner"],
        "model_core": manifest["model_core"],
        "next_permitted_action": (
            "Commit every prediction, checkpoint, sidecar, runner and replay hash before evaluator access."
            if passed
            else "Fix replay failures without evaluator access."
        ),
    }
    write_json(OUTPUT_PATH, report)
    print(f"GWM-Bench Foundation V5.0 Runtime-R4 replay: {report['status']}")
    print(f"Checks: {report['passed_check_count']}/{report['check_count']}")
    if report["failed_checks"]:
        print(f"Failed checks: {report['failed_checks']}")
    print(f"Replay report: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
