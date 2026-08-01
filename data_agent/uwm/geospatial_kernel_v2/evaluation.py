"""Fail-closed evaluators for GeoTransport and conservation tracks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


GEOTRANSPORT_EVALUATION_SCHEMA = "gwm.geotransport.evaluation.v1"
GEOCONSERVATION_EVALUATION_SCHEMA = "gwm.geoconservation.evaluation.v1"


@dataclass(frozen=True)
class EvaluationSplit:
    train_systems: tuple[str, ...]
    test_systems: tuple[str, ...]
    role: str = "internal_model_selection"

    def __post_init__(self) -> None:
        train = set(self.train_systems)
        test = set(self.test_systems)
        if not train or not test:
            raise ValueError("nonempty_train_and_test_systems_required")
        if train & test:
            raise ValueError("train_test_system_leakage")
        if self.role not in {"internal_model_selection", "external_hidden_confirmation"}:
            raise ValueError("unsupported_evaluation_role")


@dataclass(frozen=True)
class GeoTransportEvaluationSeries:
    system_ids: tuple[str, ...]
    observed: tuple[float, ...]
    predicted: tuple[float, ...]
    persistence: tuple[float, ...]
    state_only: tuple[float, ...]
    domain_baseline: tuple[float, ...] | None = None
    zero_action_prediction: tuple[float, ...] | None = None
    no_forcing_prediction: tuple[float, ...] | None = None
    reversed_topology_prediction: tuple[float, ...] | None = None
    mass_balance_residual: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        count = len(self.system_ids)
        if count == 0 or any(not system_id.strip() for system_id in self.system_ids):
            raise ValueError("evaluation_system_ids_required")
        for name in (
            "observed",
            "predicted",
            "persistence",
            "state_only",
            "domain_baseline",
            "zero_action_prediction",
            "no_forcing_prediction",
            "reversed_topology_prediction",
            "mass_balance_residual",
        ):
            values = getattr(self, name)
            if values is not None and len(values) != count:
                raise ValueError(f"{name}_length_mismatch")


def evaluate_geotransport(
    series: GeoTransportEvaluationSeries,
    *,
    split: EvaluationSplit,
    conservation_tolerance: float = 1e-6,
) -> dict[str, object]:
    """Evaluate accuracy and non-compensatory mechanism gates.

    A strong accuracy score cannot compensate for a missing action ablation,
    forcing ablation, topology reversal, or conservation test.
    """

    if not np.isfinite(conservation_tolerance) or conservation_tolerance < 0.0:
        raise ValueError("conservation_tolerance_must_be_finite_nonnegative")
    evaluated_systems = set(series.system_ids)
    if not evaluated_systems <= set(split.test_systems):
        raise ValueError("evaluation_rows_outside_test_systems")

    observed = np.asarray(series.observed, dtype=float)
    predicted = np.asarray(series.predicted, dtype=float)
    persistence = np.asarray(series.persistence, dtype=float)
    state_only = np.asarray(series.state_only, dtype=float)
    base_mask = (
        np.isfinite(observed)
        & np.isfinite(predicted)
        & np.isfinite(persistence)
        & np.isfinite(state_only)
    )
    if not bool(base_mask.any()):
        raise ValueError("no_finite_evaluation_rows")

    model_metrics = _regression_metrics(observed[base_mask], predicted[base_mask])
    persistence_metrics = _regression_metrics(
        observed[base_mask], persistence[base_mask]
    )
    state_only_metrics = _regression_metrics(
        observed[base_mask], state_only[base_mask]
    )
    domain_comparison = _baseline_comparison(
        observed, predicted, series.domain_baseline, base_mask
    )
    system_metrics: dict[str, object] = {}
    for system_id in sorted(evaluated_systems):
        mask = base_mask & (np.asarray(series.system_ids, dtype=object) == system_id)
        if bool(mask.any()):
            system_metrics[system_id] = {
                "model": _regression_metrics(observed[mask], predicted[mask]),
                "persistence": _regression_metrics(observed[mask], persistence[mask]),
                "state_only": _regression_metrics(observed[mask], state_only[mask]),
            }

    mechanism = {
        "action_ablation": _ablation_metrics(
            observed, predicted, series.zero_action_prediction, base_mask
        ),
        "forcing_ablation": _ablation_metrics(
            observed, predicted, series.no_forcing_prediction, base_mask
        ),
        "topology_reversal": _ablation_metrics(
            observed, predicted, series.reversed_topology_prediction, base_mask
        ),
        "conservation": _conservation_gate(
            series.mass_balance_residual, conservation_tolerance
        ),
    }
    standard_baseline_gate = (
        "pass"
        if model_metrics["rmse"] < persistence_metrics["rmse"]
        and model_metrics["rmse"] < state_only_metrics["rmse"]
        else "fail"
    )
    gate_statuses = {
        "accuracy_better_than_persistence_and_state_only": standard_baseline_gate,
        "accuracy_better_than_domain_baseline": domain_comparison["gate_status"],
        "action_is_necessary": mechanism["action_ablation"]["gate_status"],
        "forcing_is_necessary": mechanism["forcing_ablation"]["gate_status"],
        "authoritative_direction_is_necessary": mechanism["topology_reversal"][
            "gate_status"
        ],
        "conservation": mechanism["conservation"]["gate_status"],
    }
    if all(status == "pass" for status in gate_statuses.values()):
        overall = "pass"
    elif any(status == "fail" for status in gate_statuses.values()):
        overall = "fail"
    else:
        overall = "indeterminate"
    return {
        "schema": GEOTRANSPORT_EVALUATION_SCHEMA,
        "evaluation_role": split.role,
        "sample_count": int(base_mask.sum()),
        "missing_or_nonfinite_count": int((~base_mask).sum()),
        "train_systems": list(split.train_systems),
        "test_systems": list(split.test_systems),
        "aggregate": {
            "model": model_metrics,
            "persistence": persistence_metrics,
            "state_only": state_only_metrics,
            "domain_baseline": domain_comparison,
            "rmse_skill_over_persistence": _skill(
                model_metrics["rmse"], persistence_metrics["rmse"]
            ),
            "rmse_skill_over_state_only": _skill(
                model_metrics["rmse"], state_only_metrics["rmse"]
            ),
        },
        "by_system": system_metrics,
        "mechanism": mechanism,
        "gate_statuses": gate_statuses,
        "overall_gate_status": overall,
        "aggregation": "non_compensatory_all_gates_must_pass",
        "claim_boundary": {
            "identified_causal_action_effect": False,
            "external_hidden_confirmation": split.role == "external_hidden_confirmation",
            "general_geospatial_world_model_validated": False,
        },
    }


def evaluate_reservoir_conservation(
    *,
    observed_stock_change: Iterable[float],
    inflow_volume: Iterable[float],
    release_volume: Iterable[float],
    evaporation_volume: Iterable[float],
    other_source_sink_volume: Iterable[float] | None = None,
    tolerance: float = 1e-6,
) -> dict[str, object]:
    observed = np.asarray(tuple(observed_stock_change), dtype=float)
    inflow = np.asarray(tuple(inflow_volume), dtype=float)
    release = np.asarray(tuple(release_volume), dtype=float)
    evaporation = np.asarray(tuple(evaporation_volume), dtype=float)
    arrays = (observed, inflow, release, evaporation)
    if not observed.size or any(array.shape != observed.shape for array in arrays):
        raise ValueError("conservation_series_shape_mismatch")
    other = (
        np.zeros_like(observed)
        if other_source_sink_volume is None
        else np.asarray(tuple(other_source_sink_volume), dtype=float)
    )
    if other.shape != observed.shape:
        raise ValueError("other_source_sink_shape_mismatch")
    finite = np.logical_and.reduce([np.isfinite(array) for array in (*arrays, other)])
    if not bool(finite.any()):
        raise ValueError("no_finite_conservation_rows")
    residual = observed[finite] - (
        inflow[finite] - release[finite] - evaporation[finite] + other[finite]
    )
    gate = _conservation_gate(tuple(float(value) for value in residual), tolerance)
    return {
        "schema": GEOCONSERVATION_EVALUATION_SCHEMA,
        "sample_count": int(finite.sum()),
        "residual": {
            "mean": float(np.mean(residual)),
            "mean_absolute": float(np.mean(np.abs(residual))),
            "maximum_absolute": float(np.max(np.abs(residual))),
        },
        "gate": gate,
        "claim_boundary": {
            "unmeasured_terms_are_zero_assumption": other_source_sink_volume is None,
            "transport_validated": False,
        },
    }


def _regression_metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    error = predicted - observed
    denominator = float(np.sum((observed - observed.mean()) ** 2))
    nse = None if denominator <= 0.0 else 1.0 - float(np.sum(error**2)) / denominator
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias": float(np.mean(error)),
        "nse": nse,
    }


def _skill(model_rmse: float | None, baseline_rmse: float | None) -> float | None:
    if model_rmse is None or baseline_rmse is None or baseline_rmse <= 0.0:
        return None
    return 1.0 - model_rmse / baseline_rmse


def _ablation_metrics(
    observed: np.ndarray,
    predicted: np.ndarray,
    alternative_values: tuple[float, ...] | None,
    base_mask: np.ndarray,
) -> dict[str, object]:
    if alternative_values is None:
        return {"gate_status": "indeterminate", "reason": "ablation_not_supplied"}
    alternative = np.asarray(alternative_values, dtype=float)
    mask = base_mask & np.isfinite(alternative)
    if not bool(mask.any()):
        return {"gate_status": "indeterminate", "reason": "no_finite_ablation_rows"}
    model_rmse = float(np.sqrt(np.mean((predicted[mask] - observed[mask]) ** 2)))
    ablated_rmse = float(np.sqrt(np.mean((alternative[mask] - observed[mask]) ** 2)))
    sensitivity = float(np.mean(np.abs(predicted[mask] - alternative[mask])))
    return {
        "gate_status": "pass" if ablated_rmse > model_rmse and sensitivity > 0.0 else "fail",
        "sample_count": int(mask.sum()),
        "model_rmse": model_rmse,
        "ablated_rmse": ablated_rmse,
        "rmse_degradation": ablated_rmse - model_rmse,
        "mean_absolute_prediction_change": sensitivity,
    }


def _baseline_comparison(
    observed: np.ndarray,
    predicted: np.ndarray,
    baseline_values: tuple[float, ...] | None,
    base_mask: np.ndarray,
) -> dict[str, object]:
    if baseline_values is None:
        return {
            "gate_status": "indeterminate",
            "reason": "domain_baseline_not_supplied",
        }
    baseline = np.asarray(baseline_values, dtype=float)
    mask = base_mask & np.isfinite(baseline)
    if not bool(mask.any()):
        return {
            "gate_status": "indeterminate",
            "reason": "no_finite_domain_baseline_rows",
        }
    model_metrics = _regression_metrics(observed[mask], predicted[mask])
    baseline_metrics = _regression_metrics(observed[mask], baseline[mask])
    return {
        "gate_status": (
            "pass" if model_metrics["rmse"] < baseline_metrics["rmse"] else "fail"
        ),
        "sample_count": int(mask.sum()),
        "metrics": baseline_metrics,
        "rmse_skill": _skill(model_metrics["rmse"], baseline_metrics["rmse"]),
    }


def _conservation_gate(
    residual_values: tuple[float, ...] | None,
    tolerance: float,
) -> dict[str, object]:
    if residual_values is None:
        return {"gate_status": "indeterminate", "reason": "residual_not_supplied"}
    residual = np.asarray(residual_values, dtype=float)
    finite = residual[np.isfinite(residual)]
    if not finite.size:
        return {"gate_status": "indeterminate", "reason": "no_finite_residuals"}
    maximum = float(np.max(np.abs(finite)))
    return {
        "gate_status": "pass" if maximum <= tolerance else "fail",
        "sample_count": int(finite.size),
        "tolerance": tolerance,
        "maximum_absolute_residual": maximum,
        "mean_absolute_residual": float(np.mean(np.abs(finite))),
    }
