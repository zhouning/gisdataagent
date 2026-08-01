"""Independent scoring for an already completed outcome-free rollout."""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from .holdout_rollout import NONLINEAR_SCENARIOS, PREDICTION_SCENARIOS


HOLDOUT_SCORING_SCHEMA = "gwm.geotransport.independent_holdout_scoring.v1"


def score_holdout_rollout(
    prediction_rows: Sequence[Mapping[str, object]],
    observed_by_support_end: Mapping[str, float | None],
    *,
    prior_observation_m3s: float,
    nonlinear_conservation: Mapping[str, Mapping[str, object]],
    minimum_scored_hours: int = 1,
) -> dict[str, object]:
    """Score fixed scenarios; missing observations are omitted without imputation."""

    if not prediction_rows:
        raise ValueError("holdout_scoring_prediction_rows_required")
    prior = float(prior_observation_m3s)
    if not np.isfinite(prior) or prior < 0.0:
        raise ValueError("holdout_scoring_prior_observation_invalid")
    expected_conservation = set(NONLINEAR_SCENARIOS)
    if set(nonlinear_conservation) != expected_conservation:
        raise ValueError("holdout_scoring_conservation_scenario_set_mismatch")

    scored: dict[str, list[float]] = {
        "observed": [],
        "persistence": [],
        **{name: [] for name in PREDICTION_SCENARIOS},
    }
    scored_timestamps: list[str] = []
    missing_timestamps: list[str] = []
    previous_observation: float | None = prior
    last_support_end: str | None = None
    for row in prediction_rows:
        support_end = _required_text(row, "support_end_utc")
        if last_support_end is not None and support_end <= last_support_end:
            raise ValueError("holdout_scoring_prediction_time_axis_not_strict")
        last_support_end = support_end
        if support_end not in observed_by_support_end:
            raise ValueError("holdout_scoring_observation_axis_incomplete")
        observed = observed_by_support_end[support_end]
        if observed is None:
            missing_timestamps.append(support_end)
            previous_observation = None
            continue
        observed_value = float(observed)
        if not np.isfinite(observed_value) or observed_value < 0.0:
            raise ValueError("holdout_scoring_observation_invalid")
        if previous_observation is None:
            missing_timestamps.append(support_end)
            previous_observation = observed_value
            continue
        scored["observed"].append(observed_value)
        scored["persistence"].append(previous_observation)
        for scenario in PREDICTION_SCENARIOS:
            value = float(row[f"{scenario}_m3s"])
            if not np.isfinite(value) or value < 0.0:
                raise ValueError("holdout_scoring_prediction_invalid")
            scored[scenario].append(value)
        scored_timestamps.append(support_end)
        previous_observation = observed_value

    count = len(scored["observed"])
    if count < minimum_scored_hours:
        raise ValueError("holdout_scoring_insufficient_complete_hours")
    observed_values = np.asarray(scored["observed"], dtype=float)
    metrics = {
        name: _metrics(observed_values, np.asarray(values, dtype=float))
        for name, values in scored.items()
        if name != "observed"
    }
    central_rmse = float(metrics["nonlinear_central"]["rmse_m3s"])
    gates = {
        "central_beats_persistence_rmse": (
            central_rmse < float(metrics["persistence"]["rmse_m3s"])
        ),
        "central_beats_t_route_mc_rmse": (
            central_rmse < float(metrics["t_route_mc"]["rmse_m3s"])
        ),
        "state_only_is_worse_rmse": (
            central_rmse < float(metrics["state_only"]["rmse_m3s"])
        ),
        "zero_action_degrades_rmse": (
            central_rmse < float(metrics["zero_action"]["rmse_m3s"])
        ),
        "no_forcing_degrades_rmse": (
            central_rmse < float(metrics["no_forcing"]["rmse_m3s"])
        ),
        "reversed_topology_degrades_rmse": (
            central_rmse < float(metrics["reversed_topology"]["rmse_m3s"])
        ),
        "all_nonlinear_scenarios_conserve_mass": all(
            values.get("passed") is True
            for values in nonlinear_conservation.values()
        ),
    }
    gates["all_registered_gates_passed"] = all(gates.values())
    return {
        "schema": HOLDOUT_SCORING_SCHEMA,
        "status": "pass" if gates["all_registered_gates_passed"] else "fail",
        "scored_hour_count": count,
        "scored_support_end_utc": scored_timestamps,
        "unscored_due_to_missing_observation_or_persistence": missing_timestamps,
        "metrics": metrics,
        "registered_gates": gates,
        "support_uncertainty": {
            "lower_scenario": metrics["nonlinear_support_lower"],
            "central_scenario": metrics["nonlinear_central"],
            "upper_scenario": metrics["nonlinear_support_upper"],
            "selection_rule": "central_is_preselected;lower_and_upper_are_report_only",
        },
        "baseline_roles": {
            "persistence": "previous independent observed discharge",
            "t_route_mc": "official_domain_baseline_not_conservation_oracle",
            "direct_release": "diagnostic_not_a_routing_model",
        },
        "claim_boundary": {
            "outcome_used_by_executor": False,
            "outcome_used_only_by_independent_scorer": True,
            "bracket_selected_after_outcome_access": False,
            "single_system_validation": gates["all_registered_gates_passed"],
            "multi_system_geospatial_kernel_validated": False,
        },
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - observed
    centered = observed - float(np.mean(observed))
    denominator = float(np.sum(centered**2))
    nse = (
        float(1.0 - np.sum(error**2) / denominator)
        if denominator > 0.0
        else float("nan")
    )
    return {
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": nse,
    }


def _required_text(row: Mapping[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"holdout_scoring_{name}_required")
    return value
