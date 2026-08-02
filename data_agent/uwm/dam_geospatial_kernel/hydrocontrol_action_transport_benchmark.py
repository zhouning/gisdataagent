"""Development and held-out evaluation for HydroControl DAM-GK v0.2."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from .hydrocontrol_action_transport import (
    HYDROCONTROL_ACTION_TRANSPORT_SCHEMA,
    HydroControlActionTransportKernel,
)
from .hydrocontrol_adapter import HYDROCONTROL_ELIGIBLE_HORIZONS


HYDROCONTROL_ACTION_TRANSPORT_BENCHMARK_SCHEMA = (
    "gwm.dam_gk.hydrocontrol_action_transport_benchmark.v1"
)


def evaluate_action_transport_kernel(
    panel: pd.DataFrame,
    *,
    evaluation_year: int,
    horizons: Iterable[int] = HYDROCONTROL_ELIGIBLE_HORIZONS,
    seed: int = 31,
) -> dict[str, Any]:
    if evaluation_year < 2023:
        raise ValueError("evaluation_year_too_early")
    systems = sorted(panel["system_id"].astype(str).unique())
    if len(systems) < 3:
        raise ValueError("at_least_three_hydrocontrol_systems_required")
    horizon_reports = []
    for horizon in horizons:
        prepared = prepare_action_transport_panel(
            panel, horizon_hours=int(horizon)
        )
        folds = [
            _evaluate_fold(
                prepared,
                held_out=held_out,
                systems=systems,
                horizon_hours=int(horizon),
                evaluation_year=evaluation_year,
                seed=seed + int(horizon) * 100 + systems.index(held_out),
            )
            for held_out in systems
        ]
        horizon_reports.append(_summarize_horizon(int(horizon), folds))
    return _build_report(
        horizons=horizon_reports,
        evaluation_year=evaluation_year,
        seed=seed,
    )


def prepare_action_transport_panel(
    panel: pd.DataFrame, *, horizon_hours: int
) -> pd.DataFrame:
    if horizon_hours not in HYDROCONTROL_ELIGIBLE_HORIZONS:
        raise ValueError("unsupported_hydrocontrol_horizon")
    required = {
        "system_id",
        "timestamp",
        "effective_release_change_cfs",
        "downstream_flow_cfs",
        "admitted_current_state_action",
        "dst_transition_day",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(
            f"hydrocontrol_panel_missing_columns:{','.join(missing)}"
        )
    frame = panel.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    frame = frame.sort_values(["system_id", "timestamp"]).reset_index(drop=True)
    if frame.duplicated(["system_id", "timestamp"]).any():
        raise ValueError("duplicate_system_timestamp")
    frame["target_timestamp"] = frame["timestamp"] + pd.Timedelta(
        hours=horizon_hours
    )
    target = frame[
        ["system_id", "timestamp", "downstream_flow_cfs", "dst_transition_day"]
    ].rename(
        columns={
            "timestamp": "target_timestamp",
            "downstream_flow_cfs": "target_flow_cfs",
            "dst_transition_day": "target_dst_transition_day",
        }
    )
    frame = frame.merge(
        target,
        on=["system_id", "target_timestamp"],
        how="left",
        validate="many_to_one",
    )
    frame["target_flow_change_cfs"] = (
        frame["target_flow_cfs"] - frame["downstream_flow_cfs"]
    )
    return frame


def _evaluate_fold(
    panel: pd.DataFrame,
    *,
    held_out: str,
    systems: list[str],
    horizon_hours: int,
    evaluation_year: int,
    seed: int,
) -> dict[str, Any]:
    evaluation_start = pd.Timestamp(f"{evaluation_year}-01-01")
    evaluation_end = pd.Timestamp(f"{evaluation_year + 1}-01-01")
    valid = (
        panel["admitted_current_state_action"].fillna(False).astype(bool)
        & ~panel["dst_transition_day"].fillna(True).astype(bool)
        & ~panel["target_dst_transition_day"].fillna(True).astype(bool)
    )
    train = panel.loc[
        valid
        & (panel["system_id"] != held_out)
        & (panel["timestamp"] < evaluation_start)
        & (panel["target_timestamp"] < evaluation_start)
    ].dropna(
        subset=["effective_release_change_cfs", "target_flow_change_cfs"]
    )
    test = panel.loc[
        valid
        & (panel["system_id"] == held_out)
        & (panel["timestamp"] >= evaluation_start)
        & (panel["timestamp"] < evaluation_end)
        & (panel["target_timestamp"] < evaluation_end)
    ].dropna(
        subset=[
            "effective_release_change_cfs",
            "downstream_flow_cfs",
            "target_flow_cfs",
        ]
    )
    if train.empty or test.empty:
        raise ValueError("empty_action_transport_fold")
    kernel = HydroControlActionTransportKernel.fit(
        action_change_cfs=train["effective_release_change_cfs"].to_numpy(
            dtype=float
        ),
        future_flow_change_cfs=train["target_flow_change_cfs"].to_numpy(
            dtype=float
        ),
    )
    current = test["downstream_flow_cfs"].to_numpy(dtype=float)
    action = test["effective_release_change_cfs"].to_numpy(dtype=float)
    truth = test["target_flow_cfs"].to_numpy(dtype=float)
    prediction = kernel.predict(
        current_flow_cfs=current, action_change_cfs=action
    )
    rng = np.random.default_rng(seed)
    shuffled_action = action.copy()
    rng.shuffle(shuffled_action)
    shuffled_prediction = kernel.predict(
        current_flow_cfs=current,
        action_change_cfs=shuffled_action,
    )
    shifted_prediction = kernel.predict(
        current_flow_cfs=current,
        action_change_cfs=np.roll(action, 168),
    )
    zero_prediction = kernel.predict(
        current_flow_cfs=current,
        action_change_cfs=np.zeros_like(action),
    )
    metrics = {
        "action_transport_kernel": _flow_metrics(truth, prediction),
        "persistence": _flow_metrics(truth, current),
        "action_assignment_shuffle": _flow_metrics(
            truth, shuffled_prediction
        ),
        "temporal_shift_168": _flow_metrics(truth, shifted_prediction),
    }
    return {
        "held_out_system": held_out,
        "train_systems": [system for system in systems if system != held_out],
        "horizon_hours": horizon_hours,
        "train_sample_count": int(len(train)),
        "test_sample_count": int(len(test)),
        "seed": seed,
        "kernel": kernel.to_dict(),
        "metrics": metrics,
        "mechanism_sensitivity": {
            "mean_absolute_edge_gate_change_observed_vs_zero_action": round(
                float(np.mean(kernel.edge_gate(action))), 9
            ),
            "mean_absolute_prediction_state_change_observed_vs_zero_action": round(
                float(
                    np.mean(
                        np.abs(
                            _signed_log_state(prediction)
                            - _signed_log_state(zero_prediction)
                        )
                    )
                ),
                9,
            ),
        },
    }


def _flow_metrics(truth: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    error = prediction - truth
    scale = float(np.quantile(truth, 0.95) - np.quantile(truth, 0.05))
    if scale <= 0.0:
        raise ValueError("nonpositive_target_scale")
    return {
        "mae_cfs": round(float(np.mean(np.abs(error))), 6),
        "rmse_cfs": round(float(np.sqrt(np.mean(np.square(error)))), 6),
        "nmae_p95_p05": round(float(np.mean(np.abs(error))) / scale, 9),
    }


def _signed_log_state(values: np.ndarray) -> np.ndarray:
    return np.sign(values) * np.log1p(np.abs(values)) / 10.0


def _summarize_horizon(
    horizon_hours: int, folds: list[dict[str, Any]]
) -> dict[str, Any]:
    metric_names = tuple(folds[0]["metrics"])
    macro = {
        name: round(
            float(
                np.mean(
                    [fold["metrics"][name]["nmae_p95_p05"] for fold in folds]
                )
            ),
            9,
        )
        for name in metric_names
    }
    candidate = macro["action_transport_kernel"]
    improved_folds = sum(
        fold["metrics"]["action_transport_kernel"]["nmae_p95_p05"]
        < fold["metrics"]["persistence"]["nmae_p95_p05"]
        for fold in folds
    )
    mechanism_passed = all(
        fold["mechanism_sensitivity"][
            "mean_absolute_edge_gate_change_observed_vs_zero_action"
        ]
        > 1e-4
        and fold["mechanism_sensitivity"][
            "mean_absolute_prediction_state_change_observed_vs_zero_action"
        ]
        > 1e-4
        for fold in folds
    )
    return {
        "horizon_hours": horizon_hours,
        "folds": folds,
        "macro_nmae": macro,
        "checks": {
            "beats_persistence_macro": candidate < macro["persistence"],
            "beats_persistence_in_at_least_two_folds": improved_folds >= 2,
            "action_shuffle_degrades_macro": (
                macro["action_assignment_shuffle"] > candidate
            ),
            "temporal_shift_degrades_macro": (
                macro["temporal_shift_168"] > candidate
            ),
            "mechanism_sensitivity_above_1e_4_in_all_folds": mechanism_passed,
        },
    }


def _build_report(
    *, horizons: list[dict[str, Any]], evaluation_year: int, seed: int
) -> dict[str, Any]:
    predictive_pass_count = sum(
        row["checks"]["beats_persistence_macro"]
        and row["checks"]["beats_persistence_in_at_least_two_folds"]
        for row in horizons
    )
    action_control_pass_count = sum(
        row["checks"]["action_shuffle_degrades_macro"] for row in horizons
    )
    time_control_pass_count = sum(
        row["checks"]["temporal_shift_degrades_macro"] for row in horizons
    )
    mechanism_pass_count = sum(
        row["checks"]["mechanism_sensitivity_above_1e_4_in_all_folds"]
        for row in horizons
    )
    return {
        "schema": HYDROCONTROL_ACTION_TRANSPORT_BENCHMARK_SCHEMA,
        "kernel_schema": HYDROCONTROL_ACTION_TRANSPORT_SCHEMA,
        "protocol_id": "dam-gk-hydro-action-transport-v0.2",
        "evaluation_year": evaluation_year,
        "role": (
            "internal_model_selection"
            if evaluation_year == 2024
            else "one_time_held_out_adjudication"
        ),
        "seed": seed,
        "horizons": horizons,
        "summary": {
            "predictive_horizon_pass_count": predictive_pass_count,
            "action_control_horizon_pass_count": action_control_pass_count,
            "time_control_horizon_pass_count": time_control_pass_count,
            "mechanism_horizon_pass_count": mechanism_pass_count,
            "required_each": 3,
            "h1_gate_passed": predictive_pass_count >= 3
            and action_control_pass_count >= 3
            and mechanism_pass_count >= 3,
            "h5_action_time_gate_passed": action_control_pass_count >= 3
            and time_control_pass_count >= 3,
        },
        "claim_boundary": {
            "identified_causal_release_effect": False,
            "prospective_operational_forecast": False,
            "public_benchmark_activated": False,
            "h2_h3_h4_h6_evaluated": False,
        },
    }
