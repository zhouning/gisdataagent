"""Action-conditioned UWM simulator.

This module implements the first executable simulator boundary for UWM. The
backend is deliberately transparent and mechanistic: it proves the world-model
rollout contract and exposes every assumption in `simulator_trace`; it does not
claim empirical predictive superiority over fitted urban models.
"""

from __future__ import annotations

from typing import Any

from .contracts import UWM_ROLLOUT_TRACE_SCHEMA, validate_uwm_observation


DEFAULT_SIMULATOR_BACKEND = "mechanistic_urban_livability_v0"


def simulate_livability_rollout(
    observation: dict[str, Any],
    action_sequence: list[dict[str, Any]],
    *,
    scenario: dict[str, Any] | None = None,
    backend: str = DEFAULT_SIMULATOR_BACKEND,
    mechanism_table: dict[str, Any] | None = None,
    spatial_spillover_kernel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Roll a canonical urban observation forward under planned actions."""

    if not action_sequence:
        raise ValueError("action_sequence must not be empty")

    scenario = scenario or {"scenario_id": "baseline"}
    validation = validate_uwm_observation(observation)
    simulator_trace: list[dict[str, Any]] = [
        {
            "step": "validate_observation_contract",
            "valid": validation["valid"],
            "errors": validation["errors"],
        }
    ]
    simulator_trace.append(
        {
            "step": "read_scene_state_controls",
            "source_scene_state_id": scenario.get("source_scene_state_id"),
            "heat_stress_multiplier": _safe_float(scenario.get("heat_stress_multiplier"), default=1.0),
            "air_pollution_stress_multiplier": _safe_float(
                scenario.get("air_pollution_stress_multiplier"),
                default=1.0,
            ),
            "vulnerability_multiplier": _safe_float(scenario.get("vulnerability_multiplier"), default=1.0),
        }
    )
    mechanism_source = "hardcoded_mechanistic_coefficients"
    active_mechanism_table = None
    if mechanism_table is not None:
        mechanism_validation = _validate_mechanism_table(mechanism_table)
        simulator_trace.append(
            {
                "step": "read_data_calibrated_mechanism_table",
                "mechanism_table_id": mechanism_table.get("table_id"),
                "valid": mechanism_validation["valid"],
                "errors": mechanism_validation["errors"],
                "claim_level": (mechanism_table.get("claim_boundary") or {}).get("max_claim_level"),
                "observed_policy_outcome_superiority_claim": mechanism_table.get(
                    "observed_policy_outcome_superiority_claim"
                ),
            }
        )
        if mechanism_validation["valid"]:
            active_mechanism_table = mechanism_table
            mechanism_source = "data_calibrated_mechanism_table"
    initial_state_ref = str(observation.get("observation_id") or "unknown_observation")
    if not validation["valid"]:
        return _not_for_claim_rollout(initial_state_ref, action_sequence, scenario, backend, simulator_trace)

    units = _units_by_id(observation.get("spatial_units") or [])
    deltas = {unit_id: _zero_unit_delta() for unit_id in units}
    adjacency = _adjacency(observation.get("graph_edges") or [])
    active_spatial_kernel = None
    if spatial_spillover_kernel is not None:
        kernel_validation = _validate_spatial_spillover_kernel(
            spatial_spillover_kernel
        )
        simulator_trace.append(
            {
                "step": "read_data_calibrated_spatial_spillover_kernel",
                "kernel_id": spatial_spillover_kernel.get("kernel_id"),
                "valid": kernel_validation["valid"],
                "errors": kernel_validation["errors"],
                "claim_level": (
                    spatial_spillover_kernel.get("claim_boundary") or {}
                ).get("max_claim_level"),
                "observed_policy_outcome_superiority_claim": (
                    spatial_spillover_kernel.get(
                        "observed_policy_outcome_superiority_claim"
                    )
                ),
            }
        )
        if kernel_validation["valid"]:
            active_spatial_kernel = spatial_spillover_kernel

    for action in action_sequence:
        action_type = str(action.get("action_type") or "")
        target_units = _target_units(action, units)
        effect = _action_effect(
            action_type,
            _action_intensity(action),
            scenario,
            mechanism_table=active_mechanism_table,
        )
        simulator_trace.append(
            {
                "step": "apply_action_effects",
                "action_id": action.get("action_id"),
                "action_type": action_type,
                "target_units": target_units,
                "direct_effect": effect,
                "mechanism_source": mechanism_source,
            }
        )
        if not any(effect.values()):
            continue
        for unit_id in target_units:
            if unit_id not in deltas:
                continue
            _accumulate(deltas[unit_id], effect, 1.0)
            if active_spatial_kernel is not None:
                kernel_neighbors = _kernel_neighbors(active_spatial_kernel, unit_id)
                applied_neighbors = []
                total_factor = 0.0
                for neighbour in kernel_neighbors:
                    neighbour_id = str(neighbour.get("target_unit_id"))
                    if neighbour_id not in deltas:
                        continue
                    factor = _safe_float(
                        neighbour.get("spillover_factor"),
                        default=0.0,
                    )
                    if factor <= 0.0:
                        continue
                    _accumulate(deltas[neighbour_id], effect, factor)
                    total_factor += factor
                    applied_neighbors.append(
                        {
                            "target_unit_id": neighbour_id,
                            "spillover_factor": factor,
                            "boundary_share": _safe_float(
                                neighbour.get("boundary_share"),
                                default=0.0,
                            ),
                            "target_livability_need_score": _safe_float(
                                neighbour.get("target_livability_need_score"),
                                default=0.0,
                            ),
                        }
                    )
                simulator_trace.append(
                    {
                        "step": "apply_spatial_spillover_kernel",
                        "action_id": action.get("action_id"),
                        "source_unit_id": unit_id,
                        "kernel_id": active_spatial_kernel.get("kernel_id"),
                        "neighbor_count": len(kernel_neighbors),
                        "applied_neighbor_count": len(applied_neighbors),
                        "total_spillover_factor": round(total_factor, 9),
                        "top_applied_neighbors": applied_neighbors[:5],
                        "mechanism_source": "data_calibrated_spatial_spillover_kernel",
                    }
                )
            else:
                for neighbour_id, weight in adjacency.get(unit_id, {}).items():
                    if neighbour_id in deltas:
                        _accumulate(deltas[neighbour_id], effect, 0.35 * weight)

    for unit_delta in deltas.values():
        unit_delta["livability_delta"] = _livability_delta(unit_delta)

    aggregate = _aggregate_deltas(deltas)
    evidence_grade = _evidence_grade(observation)
    uncertainty_interval = _uncertainty_interval(aggregate["livability_delta"], observation)
    claim_boundary = {
        "max_claim_level": evidence_grade,
        "reason": _claim_reason(evidence_grade, observation),
    }
    return {
        "schema": UWM_ROLLOUT_TRACE_SCHEMA,
        "initial_state_ref": initial_state_ref,
        "action_sequence": action_sequence,
        "scenario": scenario,
        "backend": backend,
        "future_state_delta": {
            "changed_units": len([unit_id for unit_id, unit_delta in deltas.items() if _unit_changed(unit_delta)]),
            "per_unit": deltas,
            "aggregate": aggregate,
        },
        "heat_risk_delta": aggregate["heat_risk_delta"],
        "air_pollution_exposure_delta": aggregate["air_pollution_exposure_delta"],
        "service_accessibility_delta": aggregate["service_accessibility_delta"],
        "equity_delta": aggregate["equity_delta"],
        "livability_delta": aggregate["livability_delta"],
        "uncertainty_interval": uncertainty_interval,
        "evidence_grade": evidence_grade,
        "claim_boundary": claim_boundary,
        "simulator_trace": simulator_trace
        + [
            {
                "step": "aggregate_rollout_delta",
                "changed_units": len([unit_delta for unit_delta in deltas.values() if _unit_changed(unit_delta)]),
                "evidence_grade": evidence_grade,
            }
        ],
    }


def _not_for_claim_rollout(
    initial_state_ref: str,
    action_sequence: list[dict[str, Any]],
    scenario: dict[str, Any],
    backend: str,
    simulator_trace: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": UWM_ROLLOUT_TRACE_SCHEMA,
        "initial_state_ref": initial_state_ref,
        "action_sequence": action_sequence,
        "scenario": scenario,
        "backend": backend,
        "future_state_delta": {"changed_units": 0, "per_unit": {}, "aggregate": _zero_unit_delta()},
        "heat_risk_delta": 0.0,
        "air_pollution_exposure_delta": 0.0,
        "service_accessibility_delta": 0.0,
        "equity_delta": 0.0,
        "livability_delta": 0.0,
        "uncertainty_interval": {"low": 0.0, "high": 0.0},
        "evidence_grade": "not_for_claim",
        "claim_boundary": {
            "max_claim_level": "not_for_claim",
            "reason": "input observation failed uwm.canonical_observation.v1 validation",
        },
        "simulator_trace": simulator_trace,
    }


def _units_by_id(spatial_units: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(unit["unit_id"]): unit
        for unit in spatial_units
        if isinstance(unit, dict) and unit.get("unit_id") is not None
    }


def _target_units(action: dict[str, Any], units: dict[str, dict[str, Any]]) -> list[str]:
    raw_targets = action.get("target_units")
    if isinstance(raw_targets, list) and raw_targets:
        return [str(unit_id) for unit_id in raw_targets]
    target = action.get("target_unit")
    if target is not None:
        return [str(target)]
    return list(units)


def _action_intensity(action: dict[str, Any]) -> float:
    try:
        intensity = float(action.get("intensity", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(intensity, 1.0))


def _action_effect(
    action_type: str,
    intensity: float,
    scenario: dict[str, Any],
    *,
    mechanism_table: dict[str, Any] | None = None,
) -> dict[str, float]:
    heat_multiplier = _safe_float(scenario.get("heat_stress_multiplier"), default=1.0)
    air_multiplier = _safe_float(scenario.get("air_pollution_stress_multiplier"), default=1.0)
    vulnerability_multiplier = _safe_float(scenario.get("vulnerability_multiplier"), default=1.0)
    action_key = action_type.lower()
    mechanism_key = _canonical_mechanism_action_key(action_key)
    if mechanism_table is not None and mechanism_key is not None:
        coefficients = (mechanism_table.get("mechanism_coefficients") or {}).get(mechanism_key) or {}
        return {
            "heat_risk_delta": _safe_float(
                coefficients.get("heat_risk_delta"),
                default=0.0,
            )
            * intensity
            * heat_multiplier,
            "air_pollution_exposure_delta": _safe_float(
                coefficients.get("air_pollution_exposure_delta"),
                default=0.0,
            )
            * intensity
            * air_multiplier,
            "service_accessibility_delta": _safe_float(
                coefficients.get("service_accessibility_delta"),
                default=0.0,
            )
            * intensity,
            "equity_delta": _safe_float(coefficients.get("equity_delta"), default=0.0)
            * intensity
            * vulnerability_multiplier,
        }
    if action_key in {"increase_green", "increase_green_infrastructure", "urban_greening"}:
        return {
            "heat_risk_delta": -0.18 * intensity * heat_multiplier,
            "air_pollution_exposure_delta": -0.05 * intensity * air_multiplier,
            "service_accessibility_delta": 0.02 * intensity,
            "equity_delta": 0.04 * intensity * vulnerability_multiplier,
        }
    if action_key in {"cool_roof", "cool_roofs", "building_cooling_retrofit"}:
        return {
            "heat_risk_delta": -0.12 * intensity * heat_multiplier,
            "air_pollution_exposure_delta": 0.0,
            "service_accessibility_delta": 0.0,
            "equity_delta": 0.02 * intensity * vulnerability_multiplier,
        }
    if action_key in {"traffic_emission_control", "low_emission_zone"}:
        return {
            "heat_risk_delta": 0.0,
            "air_pollution_exposure_delta": -0.16 * intensity * air_multiplier,
            "service_accessibility_delta": 0.0,
            "equity_delta": 0.03 * intensity * vulnerability_multiplier,
        }
    if action_key in {"add_community_service", "service_accessibility_improvement"}:
        return {
            "heat_risk_delta": 0.0,
            "air_pollution_exposure_delta": 0.0,
            "service_accessibility_delta": 0.18 * intensity,
            "equity_delta": 0.06 * intensity * vulnerability_multiplier,
        }
    return _zero_unit_delta(include_livability=False)


def _canonical_mechanism_action_key(action_key: str) -> str | None:
    if action_key in {"increase_green", "increase_green_infrastructure", "urban_greening"}:
        return "increase_green_infrastructure"
    if action_key in {"cool_roof", "cool_roofs", "building_cooling_retrofit"}:
        return "cool_roofs"
    if action_key in {"traffic_emission_control", "low_emission_zone"}:
        return "traffic_emission_control"
    if action_key in {"add_community_service", "service_accessibility_improvement"}:
        return "add_community_service"
    return None


def _validate_mechanism_table(mechanism_table: dict[str, Any]) -> dict[str, Any]:
    try:
        from .data_calibrated_mechanism_table import (
            validate_uwm_data_calibrated_mechanism_table,
        )
    except ImportError:
        return {"valid": False, "errors": ["mechanism_table_validator_unavailable"]}
    return validate_uwm_data_calibrated_mechanism_table(mechanism_table)


def _validate_spatial_spillover_kernel(
    spatial_spillover_kernel: dict[str, Any],
) -> dict[str, Any]:
    try:
        from .spatial_spillover_kernel import (
            validate_uwm_data_calibrated_spatial_spillover_kernel,
        )
    except ImportError:
        return {"valid": False, "errors": ["spatial_spillover_kernel_validator_unavailable"]}
    return validate_uwm_data_calibrated_spatial_spillover_kernel(
        spatial_spillover_kernel
    )


def _kernel_neighbors(
    spatial_spillover_kernel: dict[str, Any],
    source_unit_id: str,
) -> list[dict[str, Any]]:
    neighbors = spatial_spillover_kernel.get("neighbors") or {}
    rows = neighbors.get(str(source_unit_id)) or []
    return [row for row in rows if isinstance(row, dict)]


def _adjacency(graph_edges: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    adjacency: dict[str, dict[str, float]] = {}
    for edge in graph_edges:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source")
        target = edge.get("target")
        if source is None or target is None:
            continue
        weight = _safe_float(edge.get("weight"), default=1.0)
        source_id = str(source)
        target_id = str(target)
        adjacency.setdefault(source_id, {})[target_id] = weight
        adjacency.setdefault(target_id, {})[source_id] = weight
    return adjacency


def _zero_unit_delta(*, include_livability: bool = True) -> dict[str, float]:
    delta = {
        "heat_risk_delta": 0.0,
        "air_pollution_exposure_delta": 0.0,
        "service_accessibility_delta": 0.0,
        "equity_delta": 0.0,
    }
    if include_livability:
        delta["livability_delta"] = 0.0
    return delta


def _accumulate(unit_delta: dict[str, float], effect: dict[str, float], factor: float) -> None:
    for key in ["heat_risk_delta", "air_pollution_exposure_delta", "service_accessibility_delta", "equity_delta"]:
        unit_delta[key] += effect.get(key, 0.0) * factor


def _livability_delta(unit_delta: dict[str, float]) -> float:
    return (
        -0.35 * unit_delta["heat_risk_delta"]
        - 0.25 * unit_delta["air_pollution_exposure_delta"]
        + 0.25 * unit_delta["service_accessibility_delta"]
        + 0.15 * unit_delta["equity_delta"]
    )


def _aggregate_deltas(deltas: dict[str, dict[str, float]]) -> dict[str, float]:
    if not deltas:
        return _zero_unit_delta()
    total = _zero_unit_delta()
    for unit_delta in deltas.values():
        for key in total:
            total[key] += unit_delta.get(key, 0.0)
    return {key: value / len(deltas) for key, value in total.items()}


def _unit_changed(unit_delta: dict[str, float]) -> bool:
    return any(abs(value) > 1e-12 for value in unit_delta.values())


def _evidence_grade(observation: dict[str, Any]) -> str:
    claim_level = str((observation.get("claim_boundary") or {}).get("max_claim_level") or "bounded_support")
    if claim_level in {"not_for_claim", "exploratory_only", "fragile"}:
        return claim_level
    synthetic_statuses = {str(flag.get("status") or "") for flag in observation.get("synthetic_flags") or []}
    if synthetic_statuses.intersection({"synthetic", "semi_synthetic", "smoke_only"}):
        return "exploratory_only"
    return "bounded_support"


def _claim_reason(evidence_grade: str, observation: dict[str, Any]) -> str:
    if evidence_grade == "not_for_claim":
        return "observation cannot support claims"
    if evidence_grade == "exploratory_only":
        return "rollout depends on synthetic or exploratory observation inputs"
    if evidence_grade == "fragile":
        return "observation claim boundary is fragile"
    if observation.get("synthetic_flags"):
        return "rollout uses public proxy inputs and supports bounded claims only"
    return "transparent mechanism rollout over canonical urban observation"


def _uncertainty_interval(livability_delta: float, observation: dict[str, Any]) -> dict[str, float]:
    statuses = {str(flag.get("status") or "") for flag in observation.get("synthetic_flags") or []}
    width = max(0.02, abs(livability_delta) * 0.35)
    if "public_proxy" in statuses:
        width += 0.02
    if statuses.intersection({"synthetic", "semi_synthetic", "smoke_only"}):
        width += 0.05
    return {"low": livability_delta - width, "high": livability_delta + width}


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
