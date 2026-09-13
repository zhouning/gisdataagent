#!/usr/bin/env python3
"""Run V5 Runtime-R4 predictions without opening any outer-fold answer file."""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
import torch

from action_transfer_evaluator import validate_submission
from v5_runtime_models import (
    ACTION_COLUMNS,
    CONFIGS,
    STATE_COLUMNS,
    action_control_inputs,
    final_crossfit_examples,
    fit_ridge_models,
    load_development,
    load_relations,
    load_test_input,
    prediction_frame,
    predict_residual,
    predict_ridge_recursive,
    save_checkpoint,
    select_residual_config,
    sha256_file,
    smoke_config,
    test_residual_example,
    train_residual_model,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
SEAL_PATH = DRAFT_ROOT / "runtime_r4_evaluator_seal.json"
RUNTIME_PATH = DRAFT_ROOT / "runtime_r4_contract.json"
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
SUBMISSION_CONTRACT_PATH = DRAFT_ROOT / "submission_contract.json"
MODEL_CORE_PATH = DRAFT_ROOT / "v5_runtime_models.py"
FORMAL_ROOT = DRAFT_ROOT / "predictions"
SMOKE_ROOT = DRAFT_ROOT / "smoke_runtime_r4"


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


def assert_model_read_allowed(path: Path) -> None:
    resolved = path.resolve()
    if "test_targets" in resolved.parts:
        raise PermissionError(f"Runtime-R4 model process denied answer path: {resolved}")


def audited_parquet(path: Path, reads: list[dict[str, Any]]) -> pd.DataFrame:
    assert_model_read_allowed(path)
    frame = pd.read_parquet(path)
    reads.append(artifact(path))
    return frame


def audited_json(path: Path, reads: list[dict[str, Any]]) -> dict[str, Any]:
    assert_model_read_allowed(path)
    payload = load_json(path)
    reads.append(artifact(path))
    return payload


def environment_payload() -> dict[str, Any]:
    return {
        "schema": "gwm_bench.foundation_v5_runtime_environment.v1",
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


def ensemble_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        raise ValueError("cannot ensemble an empty frame list")
    key_columns = ["fold_id", "zone_id", "horizon_week"]
    prediction_columns = [f"{target}_prediction" for target in STATE_COLUMNS]
    ordered = [frame.sort_values(key_columns).reset_index(drop=True) for frame in frames]
    base = ordered[0][key_columns].copy()
    for frame in ordered[1:]:
        if not base.equals(frame[key_columns]):
            raise ValueError("ensemble member key mismatch")
    for column in prediction_columns:
        base[column] = np.mean(
            [frame[column].to_numpy(dtype=np.float64) for frame in ordered], axis=0
        )
    return base


def validate_fold_frame(frame: pd.DataFrame, fold_id: str, expected: pd.DataFrame) -> None:
    key_columns = ["fold_id", "zone_id", "horizon_week"]
    prediction_columns = [f"{target}_prediction" for target in STATE_COLUMNS]
    if len(frame) != 3156 or frame["fold_id"].nunique() != 1:
        raise ValueError(f"wrong smoke/fold prediction rows: {fold_id}")
    actual_keys = frame[key_columns].sort_values(key_columns).reset_index(drop=True)
    expected_keys = expected[key_columns].sort_values(key_columns).reset_index(drop=True)
    actual_keys["zone_id"] = actual_keys["zone_id"].astype(np.int64)
    actual_keys["horizon_week"] = actual_keys["horizon_week"].astype(np.int64)
    expected_keys["zone_id"] = expected_keys["zone_id"].astype(np.int64)
    expected_keys["horizon_week"] = expected_keys["horizon_week"].astype(np.int64)
    if not actual_keys.equals(expected_keys):
        raise ValueError(f"fold key mismatch: {fold_id}")
    values = frame[prediction_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError(f"invalid prediction values: {fold_id}")


def write_fold_member(
    output_root: Path,
    model_id: str,
    fold_id: str,
    frame: pd.DataFrame,
    *,
    seed: int | None,
    checkpoint: Path | None = None,
    training: dict[str, Any] | None = None,
    control_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if seed is None:
        root = output_root / model_id / "folds" / fold_id
    else:
        root = output_root / model_id / "members" / f"seed_{seed}" / "folds" / fold_id
    root.mkdir(parents=True, exist_ok=True)
    prediction_path = root / "prediction.parquet"
    frame.to_parquet(prediction_path, index=False)
    report = {
        "schema": "gwm_bench.foundation_v5_fold_prediction_run.v1",
        "model_id": model_id,
        "outer_fold_id": fold_id,
        "seed": seed,
        "prediction": artifact(prediction_path),
        "checkpoint": artifact(checkpoint) if checkpoint is not None else None,
        "training_final_loss": (
            training["history"][-1]["smooth_l1"] if training is not None else None
        ),
        "control_audit": control_audit,
        "model_process_target_access_permitted": False,
        "test_target_rows_loaded": False,
        "exit_status": "success",
        "failure_state": None,
    }
    write_json(root / "run_report.json", report)
    return report


def fold_paths(fold: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Path]:
    root = REPO_ROOT / fold["fold_root"]
    firewall = runtime["contracts"]["OuterFoldFirewall"]
    return {
        "root": root,
        "development": root / firewall["development_relative_path"],
        "history": root / firewall["history_relative_path"],
        "action": root / firewall["action_relative_path"],
        "keys": root / firewall["submission_keys_relative_path"],
        "graph": root / firewall["test_graph_relative_path"],
        "zone_metadata": root / "graph/zone_metadata.parquet",
        "training_manifest": root / "development/training_row_manifest.json",
        "training_graph_index": root / "graph/training_graph_index.json",
    }


def verify_frozen_boundary(seal: dict[str, Any]) -> None:
    if seal["status"] != "RUNTIME_R4_EVALUATOR_SEALED_PREDICTIONS_PENDING":
        raise ValueError("Runtime-R4/evaluator is not in predictions-pending state")
    for name, path in {
        "protocol": PROTOCOL_PATH,
        "runtime_r4_contract": RUNTIME_PATH,
        "submission_contract": SUBMISSION_CONTRACT_PATH,
    }.items():
        frozen = seal["artifacts"][name]
        if path.stat().st_size != frozen["bytes"] or sha256_file(path) != frozen["sha256"]:
            raise ValueError(f"frozen artifact changed before prediction: {name}")


def run_fold(
    fold: dict[str, Any],
    runtime: dict[str, Any],
    output_root: Path,
    *,
    seeds: tuple[int, ...],
    smoke: bool,
) -> dict[str, Any]:
    fold_started = time.monotonic()
    fold_id = fold["fold_id"]
    paths = fold_paths(fold, runtime)
    reads: list[dict[str, Any]] = []
    for path in paths.values():
        if path != paths["root"]:
            assert_model_read_allowed(path)

    development_frame = audited_parquet(paths["development"], reads)
    development_temp = output_root / "_runtime_cache" / fold_id / "development.parquet"
    development_temp.parent.mkdir(parents=True, exist_ok=True)
    development_frame.to_parquet(development_temp, index=False)
    events = load_development(development_temp, fold["training_events"])
    test = load_test_input(paths["history"], paths["action"])
    reads.extend([artifact(paths["history"]), artifact(paths["action"])])
    expected_keys = audited_parquet(paths["keys"], reads)
    expected_keys.insert(0, "fold_id", fold_id)
    zone_metadata = audited_parquet(paths["zone_metadata"], reads)
    test_relations, test_graph_audit = load_relations(paths["graph"])
    reads.append(artifact(paths["graph"]))
    graph_index = audited_json(paths["training_graph_index"], reads)
    training_manifest = audited_json(paths["training_manifest"], reads)
    relations_by_event: dict[str, np.ndarray] = {}
    graph_audits: dict[str, Any] = {}
    for event_id in fold["training_events"]:
        graph_path = REPO_ROOT / graph_index["training_event_graphs"][event_id]["path"]
        assert_model_read_allowed(graph_path)
        relations, graph_audit = load_relations(graph_path)
        reads.append(artifact(graph_path))
        relations_by_event[event_id] = relations
        graph_audits[event_id] = graph_audit
    adjacency = test_relations[0]

    if smoke:
        selected_config = smoke_config()
        selection_report = {
            "schema": "gwm_bench.foundation_v5_nested_selection_receipt.v1",
            "outer_fold_id": fold_id,
            "mode": "smoke_no_formal_selection",
            "selected_config": selected_config.name,
            "formal_prediction_permitted": False,
        }
    else:
        selected_config, selection_report = select_residual_config(
            events,
            relations_by_event,
            adjacency,
            seed=31,
            configs=CONFIGS,
        )
        selection_report.update(
            {
                "schema": "gwm_bench.foundation_v5_nested_selection_receipt.v1",
                "outer_fold_id": fold_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "candidate_grid_sha256": sha256_file(MODEL_CORE_PATH),
                "training_event_ids": fold["training_events"],
                "current_outer_fold_targets_read": False,
            }
        )

    history_models = fit_ridge_models(events, adjacency, spatial=False, alpha=5.0)
    history_prediction = predict_ridge_recursive(
        history_models, test, adjacency, spatial=False
    )
    spatial_models = fit_ridge_models(events, adjacency, spatial=True, alpha=5.0)
    spatial_prediction = predict_ridge_recursive(
        spatial_models, test, adjacency, spatial=True
    )
    history_frame = prediction_frame(fold_id, history_prediction)
    spatial_frame = prediction_frame(fold_id, spatial_prediction)
    validate_fold_frame(history_frame, fold_id, expected_keys)
    validate_fold_frame(spatial_frame, fold_id, expected_keys)
    history_report = write_fold_member(
        output_root, "history_ar_backbone", fold_id, history_frame, seed=None
    )
    spatial_report = write_fold_member(
        output_root, "fixed_adjacency_spatial_ar", fold_id, spatial_frame, seed=None
    )

    training_examples = final_crossfit_examples(events, relations_by_event, adjacency)
    test_example = test_residual_example(
        fold["test_event"], test, history_prediction, test_relations
    )
    swap_source = sorted(events)[0]
    swap_action = events[swap_source].action[52:].copy()
    fold_frames_by_model: dict[str, dict[int | None, pd.DataFrame]] = {
        "history_ar_backbone": {None: history_frame},
        "fixed_adjacency_spatial_ar": {None: spatial_frame},
    }
    fold_run_reports: dict[str, Any] = {
        "history_ar_backbone": history_report,
        "fixed_adjacency_spatial_ar": spatial_report,
    }
    controls = runtime["required_controls"]
    for seed in seeds:
        for model_id, action_conditioned in (
            ("uwm_dam_gk_action_residual", True),
            ("dam_gk_residual_no_action", False),
        ):
            started = time.monotonic()
            model, scaler, training = train_residual_model(
                training_examples,
                selected_config,
                seed,
                action_conditioned=action_conditioned,
            )
            prediction, raw_delta = predict_residual(
                model,
                scaler,
                test_example,
                action_conditioned=action_conditioned,
            )
            frame = prediction_frame(fold_id, prediction)
            validate_fold_frame(frame, fold_id, expected_keys)
            member_root = (
                output_root
                / model_id
                / "members"
                / f"seed_{seed}"
                / "folds"
                / fold_id
            )
            checkpoint_path = member_root / "model.pt"
            delta_path = member_root / "raw_action_residual.parquet"
            save_checkpoint(checkpoint_path, model, scaler, training)
            prediction_frame(fold_id, raw_delta).to_parquet(delta_path, index=False)
            report = write_fold_member(
                output_root,
                model_id,
                fold_id,
                frame,
                seed=seed,
                checkpoint=checkpoint_path,
                training=training,
            )
            report["wall_seconds"] = time.monotonic() - started
            report["raw_action_residual"] = artifact(delta_path)
            write_json(member_root / "run_report.json", report)
            fold_frames_by_model.setdefault(model_id, {})[seed] = frame
            fold_run_reports[f"{model_id}/seed_{seed}"] = report

            if action_conditioned:
                for control_id in controls:
                    future, age, relations, control_audit = action_control_inputs(
                        control_id,
                        test_example,
                        zone_metadata,
                        swap_action=swap_action,
                    )
                    control_prediction, _ = predict_residual(
                        model,
                        scaler,
                        test_example,
                        relations=relations,
                        action_future=future,
                        action_age=age,
                        action_conditioned=True,
                    )
                    control_frame = prediction_frame(fold_id, control_prediction)
                    validate_fold_frame(control_frame, fold_id, expected_keys)
                    control_audit.update(
                        {
                            "outer_fold_id": fold_id,
                            "swap_source_event": (
                                swap_source
                                if control_id == "cross_event_action_swap"
                                else None
                            ),
                        }
                    )
                    control_report = write_fold_member(
                        output_root,
                        control_id,
                        fold_id,
                        control_frame,
                        seed=seed,
                        control_audit=control_audit,
                    )
                    fold_frames_by_model.setdefault(control_id, {})[
                        seed
                    ] = control_frame
                    fold_run_reports[f"{control_id}/seed_{seed}"] = control_report

    selection_path = output_root / "folds" / fold_id / "nested_selection_receipt.json"
    write_json(selection_path, selection_report)
    fold_report = {
        "schema": "gwm_bench.foundation_v5_outer_fold_run.v1",
        "outer_fold_id": fold_id,
        "test_event": fold["test_event"],
        "training_events": fold["training_events"],
        "mode": "smoke" if smoke else "formal",
        "selected_config": selected_config.name,
        "selection_receipt": artifact(selection_path),
        "training_manifest": training_manifest,
        "test_graph": test_graph_audit,
        "training_graphs": graph_audits,
        "model_read_artifacts": reads,
        "model_read_path_count": len(reads),
        "model_read_paths_contain_answer_directory": any(
            "test_targets" in (REPO_ROOT / row["path"]).parts for row in reads
        ),
        "test_target_rows_loaded": False,
        "fold_prediction_reports": fold_run_reports,
        "wall_seconds": time.monotonic() - fold_started,
        "ru_maxrss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "exit_status": "success",
        "failure_state": None,
    }
    fold_report_path = output_root / "folds" / fold_id / "run_report.json"
    write_json(fold_report_path, fold_report)
    return {
        "fold_id": fold_id,
        "frames": fold_frames_by_model,
        "expected_keys": expected_keys,
        "selection_report": selection_report,
        "selection_path": selection_path,
        "training_manifest": training_manifest,
        "fold_report": fold_report,
        "fold_report_path": fold_report_path,
    }


def write_model_bundle(
    output_root: Path,
    model_id: str,
    frame: pd.DataFrame,
    *,
    runtime: dict[str, Any],
    selections: dict[str, Any],
    training_manifests: dict[str, Any],
    fold_reports: dict[str, Any],
    seeds: tuple[int, ...] | None,
) -> dict[str, Any]:
    root = output_root / model_id
    root.mkdir(parents=True, exist_ok=True)
    prediction_path = root / "prediction.parquet"
    model_spec_path = root / "model_spec.json"
    selection_path = root / "nested_selection_receipts.json"
    manifests_path = root / "fold_training_manifests.json"
    environment_path = root / "runtime_environment.json"
    report_path = root / "run_report.json"
    frame.to_parquet(prediction_path, index=False)
    is_candidate = model_id == "uwm_dam_gk_action_residual"
    is_no_action = model_id == "dam_gk_residual_no_action"
    is_control = model_id in runtime["required_controls"]
    algorithm = (
        "fixed V4-style per-zone Ridge history AR backbone"
        if model_id == "history_ar_backbone"
        else "fixed-adjacency per-zone Ridge spatial AR"
        if model_id == "fixed_adjacency_spatial_ar"
        else "DAM-GK multi-relation neural residual kernel over a frozen history AR forecast"
    )
    write_json(
        model_spec_path,
        {
            "schema": "gwm_bench.foundation_v5_model_spec.v1",
            "model_id": model_id,
            "algorithm": algorithm,
            "prediction_equation": (
                "final = frozen_history_ar + dam_gk_residual"
                if is_candidate or is_no_action or is_control
                else None
            ),
            "action_conditioned": is_candidate or is_control,
            "matched_no_action": is_no_action,
            "control": is_control,
            "seeds": list(seeds) if seeds is not None else [],
            "ensemble_rule": (
                "arithmetic mean in raw count space" if seeds is not None else None
            ),
            "lags": [1, 2, 4, 8],
            "history_ar_alpha": 5.0,
            "current_outer_fold_targets_read": False,
        },
    )
    write_json(
        selection_path,
        {
            "schema": "gwm_bench.foundation_v5_nested_selection_receipts.v1",
            "model_id": model_id,
            "receipts": selections,
            "current_outer_fold_targets_read": False,
        },
    )
    write_json(
        manifests_path,
        {
            "schema": "gwm_bench.foundation_v5_fold_training_manifests.v1",
            "model_id": model_id,
            "manifests": training_manifests,
            "heldout_event_rows_loaded": 0,
            "heldout_post_action_target_rows_loaded": 0,
        },
    )
    write_json(environment_path, environment_payload())
    report = {
        "schema": "gwm_bench.foundation_v5_multifold_run_report.v1",
        "model_id": model_id,
        "outer_fold_count": 4,
        "seed_count": len(seeds) if seeds is not None else 0,
        "fold_reports": fold_reports,
        "prediction": artifact(prediction_path),
        "model_spec": artifact(model_spec_path),
        "nested_selection_receipts": artifact(selection_path),
        "fold_training_manifests": artifact(manifests_path),
        "runtime_environment": artifact(environment_path),
        "test_target_rows_loaded": False,
        "model_process_target_access_permitted": False,
        "exit_status": "success",
        "failure_state": None,
    }
    write_json(report_path, report)
    return {
        "prediction_path": str(prediction_path.relative_to(REPO_ROOT)),
        "prediction_artifact": artifact(prediction_path),
        "model_spec": artifact(model_spec_path),
        "nested_selection_receipts": artifact(selection_path),
        "fold_training_manifests": artifact(manifests_path),
        "runtime_environment": artifact(environment_path),
        "run_report": artifact(report_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "formal"), default="smoke")
    parser.add_argument("--fold", choices=("holdout_2015", "holdout_2019", "holdout_2022", "holdout_2025"))
    args = parser.parse_args()
    smoke = args.mode == "smoke"
    output_root = SMOKE_ROOT if smoke else FORMAL_ROOT
    seal = load_json(SEAL_PATH)
    runtime = load_json(RUNTIME_PATH)
    contract = load_json(SUBMISSION_CONTRACT_PATH)
    verify_frozen_boundary(seal)
    if "current_fold/test_targets" not in runtime["read_routes"][
        "model_runtime_denied_per_current_fold"
    ]:
        raise ValueError("unexpected Runtime-R4 answer-denial route")
    selected_folds = runtime["outer_folds"]
    if args.fold is not None:
        selected_folds = [fold for fold in selected_folds if fold["fold_id"] == args.fold]
    elif smoke:
        selected_folds = selected_folds[:1]
    if not smoke and len(selected_folds) != 4:
        raise ValueError("formal Runtime-R4 must run all four outer folds")
    seeds = (31,) if smoke else tuple(runtime["stochastic_seed_contract"]["required_seeds"])
    started = time.monotonic()
    fold_results = [
        run_fold(fold, runtime, output_root, seeds=seeds, smoke=smoke)
        for fold in selected_folds
    ]

    if smoke:
        report = {
            "schema": "gwm_bench.foundation_v5_runtime_r4_smoke.v1",
            "suite_id": seal["suite_id"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "PASS_RUNTIME_R4_SMOKE_NO_TARGET_ACCESS",
            "formal_predictions_created": False,
            "folds": [result["fold_report"] for result in fold_results],
            "runner": artifact(Path(__file__)),
            "model_core": artifact(MODEL_CORE_PATH),
            "wall_seconds": time.monotonic() - started,
        }
        report_path = output_root / "smoke_report.json"
        write_json(report_path, report)
        print("GWM-Bench Foundation V5.0: PASS_RUNTIME_R4_SMOKE_NO_TARGET_ACCESS")
        print(f"Smoke report: {report_path}")
        return 0

    expected_keys = pd.concat(
        [result["expected_keys"] for result in fold_results], ignore_index=True
    )
    selections = {
        result["fold_id"]: result["selection_report"] for result in fold_results
    }
    training_manifests = {
        result["fold_id"]: result["training_manifest"] for result in fold_results
    }
    fold_reports = {
        result["fold_id"]: artifact(result["fold_report_path"])
        for result in fold_results
    }
    required_ids = [*runtime["required_models"], *runtime["required_controls"]]
    submissions: dict[str, Any] = {}
    for model_id in required_ids:
        if model_id in runtime["deterministic_submission_ids"]:
            multifold = pd.concat(
                [result["frames"][model_id][None] for result in fold_results],
                ignore_index=True,
            )
            seeds_for_model = None
        else:
            member_frames = []
            for seed in seeds:
                member = pd.concat(
                    [result["frames"][model_id][seed] for result in fold_results],
                    ignore_index=True,
                ).sort_values(["fold_id", "zone_id", "horizon_week"]).reset_index(drop=True)
                member_path = output_root / model_id / "members" / f"seed_{seed}" / "prediction.parquet"
                member.to_parquet(member_path, index=False)
                write_json(
                    member_path.with_name("run_report.json"),
                    {
                        "schema": "gwm_bench.foundation_v5_seed_multifold_run.v1",
                        "model_id": model_id,
                        "seed": seed,
                        "outer_fold_count": 4,
                        "prediction": artifact(member_path),
                        "test_target_rows_loaded": False,
                        "exit_status": "success",
                    },
                )
                member_frames.append(member)
            multifold = ensemble_frames(member_frames)
            seeds_for_model = seeds
        validated = validate_submission(multifold, expected_keys, contract)
        submissions[model_id] = write_model_bundle(
            output_root,
            model_id,
            validated,
            runtime=runtime,
            selections=selections,
            training_manifests=training_manifests,
            fold_reports=fold_reports,
            seeds=seeds_for_model,
        )

    manifest = {
        "schema": "gwm_bench.foundation_v5_prediction_manifest_draft.v1",
        "suite_id": seal["suite_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ALL_REQUIRED_MULTIFOLD_PREDICTIONS_MATERIALIZED_UNCOMMITTED",
        "test_target_rows_loaded": False,
        "runtime_seal": artifact(SEAL_PATH),
        "runtime_contract": artifact(RUNTIME_PATH),
        "submission_contract": artifact(SUBMISSION_CONTRACT_PATH),
        "runner": artifact(Path(__file__)),
        "model_core": artifact(MODEL_CORE_PATH),
        "required_models": runtime["required_models"],
        "required_controls": runtime["required_controls"],
        "required_seeds": list(seeds),
        "required_outer_folds": [fold["fold_id"] for fold in selected_folds],
        "submissions": submissions,
        "wall_seconds": time.monotonic() - started,
        "ru_maxrss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    manifest_path = output_root / "prediction_manifest_draft.json"
    write_json(manifest_path, manifest)
    print(
        "GWM-Bench Foundation V5.0: "
        "ALL_REQUIRED_MULTIFOLD_PREDICTIONS_MATERIALIZED_UNCOMMITTED"
    )
    print(f"Prediction manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
