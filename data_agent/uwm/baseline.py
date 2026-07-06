"""Traditional livability baseline for UWM comparisons."""

from __future__ import annotations

from typing import Any


def compute_traditional_livability_baseline(
    records: list[dict[str, Any]],
    indicators: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compute a static weighted-indicator livability baseline.

    This is intentionally not a world model. It has no action-conditioned
    transition, no rollout and no evidence gate; UWM must beat this baseline
    on dynamic and counterfactual tasks later.
    """

    values_by_indicator = {
        name: [_safe_float(row.get(name)) for row in records]
        for name in indicators
    }
    scores = []
    total_weight = sum(_safe_float(config.get("weight"), default=0.0) for config in indicators.values()) or 1.0
    for row in records:
        score = 0.0
        components = {}
        for name, config in indicators.items():
            raw_value = _safe_float(row.get(name))
            norm = _normalise(raw_value, values_by_indicator[name])
            if config.get("direction") == "negative":
                norm = 1.0 - norm
            weight = _safe_float(config.get("weight"), default=0.0)
            contribution = weight * norm / total_weight
            components[name] = {
                "raw": raw_value,
                "normalised": norm,
                "weight": weight,
                "contribution": contribution,
            }
            score += contribution
        scores.append(
            {
                "unit_id": row.get("unit_id"),
                "score": score,
                "components": components,
            }
        )
    scores.sort(key=lambda item: item["score"], reverse=True)
    return {
        "schema": "uwm.traditional_livability_baseline.v1",
        "method": "static_weighted_indicator_overlay",
        "action_conditioned": False,
        "dynamic_rollout": False,
        "scores": scores,
        "limitations": [
            "no action-conditioned transition",
            "no simulator trace",
            "no counterfactual rollout",
            "no spatial causal evidence gate",
            "sensitive to indicator weighting and normalisation",
        ],
    }


def build_baseline_vs_uwm_capability_report(
    baseline: dict[str, Any],
    observation: dict[str, Any],
) -> dict[str, Any]:
    """Compare static baseline capability with current UWM contract coverage."""

    uwm_contract = {
        "canonical_observation": observation.get("schema") == "uwm.canonical_observation.v1",
        "graph_context": bool(observation.get("graph_edges")),
        "renderer_trace": bool(observation.get("renderer_trace")),
        "claim_boundary": bool(observation.get("claim_boundary")),
    }
    remaining_gates = []
    if not baseline.get("dynamic_rollout"):
        remaining_gates.append("dynamic_rollout_required_for_superiority_claim")
    remaining_gates.append("simulator_holdout_required_for_empirical_superiority")
    remaining_gates.append("planner_regret_required_for_policy_superiority")
    return {
        "schema": "uwm.baseline_comparison_report.v1",
        "traditional_baseline": {
            "static_scores_available": bool(baseline.get("scores")),
            "action_conditioned": bool(baseline.get("action_conditioned")),
            "dynamic_rollout": bool(baseline.get("dynamic_rollout")),
            "method": baseline.get("method"),
        },
        "uwm_contract": uwm_contract,
        "current_advantages": [
            key
            for key, value in uwm_contract.items()
            if value and key in {"canonical_observation", "graph_context", "renderer_trace", "claim_boundary"}
        ],
        "remaining_gates": remaining_gates,
    }


def _normalise(value: float, values: list[float]) -> float:
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return 0.5
    return (value - minimum) / (maximum - minimum)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
