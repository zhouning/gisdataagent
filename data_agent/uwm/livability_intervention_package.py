"""Business-theory aligned livability intervention package for UWM outputs."""

from __future__ import annotations

from typing import Any


UWM_LIVABILITY_INTERVENTION_PACKAGE_SCHEMA = "uwm.livability_intervention_package.v1"

RESULT_SHAPE = [
    "low_livability_area_identification",
    "mechanism_explanation",
    "intervention_suitability_map",
    "multi_step_action_sequence",
    "before_after_indicator_delta",
    "equity_conclusion",
    "evidence_boundary",
]

TARGET_DIRECTIONS = {
    "heat_risk_delta": "target_decrease",
    "air_pollution_exposure_delta": "target_decrease",
    "service_accessibility_delta": "target_increase",
    "equity_delta": "target_increase",
    "livability_delta": "target_increase",
}

MECHANISM_ACTION_PRIORITY = {
    "service_accessibility_deficit": "add_community_service",
    "heat_risk_exposure": "increase_green_infrastructure",
    "air_pollution_exposure": "traffic_emission_control",
    "equity_priority": "add_community_service",
}


def build_livability_intervention_package(
    *,
    search_report: dict[str, Any],
    learned_rollout_report: dict[str, Any],
    synthetic_policy_outcome_benchmark: dict[str, Any],
    tap_like_pm25_scene_manifest: dict[str, Any] | None = None,
    package_id: str,
    created_at: str,
    low_unit_limit: int = 10,
) -> dict[str, Any]:
    """Convert UWM world-model reports into an evidence-gated planning package."""

    graph_state = search_report.get("graph_mdp_state") or {}
    nodes = list(graph_state.get("nodes") or [])
    if not nodes:
        raise ValueError("livability intervention package requires graph_mdp_state nodes")

    available_actions = list(graph_state.get("available_actions") or [])
    low_units = _low_livability_units(nodes, limit=low_unit_limit)
    mechanism_explanations = [_mechanism_explanation(unit) for unit in low_units]
    intervention_suitability = [
        _intervention_suitability(unit, available_actions)
        for unit in low_units
    ]
    selected_sequence = (
        (learned_rollout_report.get("learned_rollout_planner") or {}).get("selected_sequence")
        or {}
    )
    before_after_indicators = _before_after_indicators(
        nodes,
        list(selected_sequence.get("action_sequence") or []),
        list(selected_sequence.get("imagined_steps") or []),
    )
    equity_conclusion = _equity_conclusion(low_units, before_after_indicators)
    comparison = _traditional_method_comparison(
        learned_rollout_report,
        synthetic_policy_outcome_benchmark,
    )
    supported_claim = _supported_claim(learned_rollout_report, comparison)
    remaining_gates = _remaining_gates(
        learned_rollout_report,
        synthetic_policy_outcome_benchmark,
    )
    evidence_boundary = _evidence_boundary(
        search_report,
        learned_rollout_report,
        synthetic_policy_outcome_benchmark,
        tap_like_pm25_scene_manifest,
        supported_claim=supported_claim,
        remaining_gates=remaining_gates,
    )

    return {
        "schema": UWM_LIVABILITY_INTERVENTION_PACKAGE_SCHEMA,
        "package_id": package_id,
        "created_at": created_at,
        "source_report_schema": search_report.get("schema"),
        "source_learned_rollout_schema": learned_rollout_report.get("schema"),
        "source_synthetic_policy_outcome_schema": synthetic_policy_outcome_benchmark.get("schema"),
        "source_tap_like_pm25_scene_schema": (
            tap_like_pm25_scene_manifest or {}
        ).get("schema"),
        "business_theory_alignment": {
            "theory_basis": [
                "environmental_health_risk",
                "public_service_accessibility",
                "spatial_equity_and_environmental_justice",
                "urban_complex_system_dynamics",
                "planning_feasibility_constraints",
            ],
            "result_shape": RESULT_SHAPE,
            "indicator_contract": TARGET_DIRECTIONS,
            "planning_action_contract": MECHANISM_ACTION_PRIORITY,
        },
        "low_livability_units": low_units,
        "mechanism_explanations": mechanism_explanations,
        "intervention_suitability": intervention_suitability,
        "multi_step_plan": _multi_step_plan(selected_sequence),
        "before_after_indicators": before_after_indicators,
        "equity_conclusion": equity_conclusion,
        "traditional_method_comparison": comparison,
        "supported_claim": supported_claim,
        "empirical_superiority_claim": False,
        "synthetic_status": "synthetic",
        "quality_status": "business_theory_aligned_proxy_and_synthetic_intervention_package",
        "claim_boundary": {
            "max_claim_level": "exploratory_only",
            "reason": (
                "package includes simulator or semi-synthetic policy-outcome evidence; "
                "observed intervention outcomes and authoritative air-quality holdout remain required"
            ),
        },
        "evidence_boundary": evidence_boundary,
        "remaining_gates": remaining_gates,
    }


def _low_livability_units(
    nodes: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    ranked = []
    for node in nodes:
        unit_id = str(node.get("unit_id") or node.get("node_id") or "")
        if not unit_id:
            continue
        features = _normalise_features(node.get("features") or node)
        mechanisms = _dominant_mechanisms(features)
        score = _low_livability_priority_score(features)
        ranked.append(
            {
                "unit_id": unit_id,
                "indicators": {key: round(value, 9) for key, value in features.items()},
                "livability_gap": round(1.0 - features["livability"], 9),
                "priority_score": round(score, 9),
                "dominant_mechanisms": mechanisms,
            }
        )

    ranked.sort(
        key=lambda item: (
            item["priority_score"],
            item["livability_gap"],
            1.0 - item["indicators"]["service_accessibility"],
            item["indicators"]["heat_risk"],
            item["indicators"]["air_pollution_exposure"],
        ),
        reverse=True,
    )
    return [
        {
            "rank": index,
            **item,
        }
        for index, item in enumerate(ranked[: max(1, limit)], start=1)
    ]


def _mechanism_explanation(unit: dict[str, Any]) -> dict[str, Any]:
    mechanisms = list(unit.get("dominant_mechanisms") or ["multi_factor_livability_gap"])
    primary = mechanisms[0]
    return {
        "unit_id": unit["unit_id"],
        "primary_mechanism": primary,
        "dominant_mechanisms": mechanisms,
        "mechanism_summary": _mechanism_summary(primary),
        "indicator_evidence": unit["indicators"],
    }


def _intervention_suitability(
    unit: dict[str, Any],
    available_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    mechanisms = list(unit.get("dominant_mechanisms") or [])
    recommended_type = _recommended_action_type(mechanisms)
    matching_actions = [
        _public_action(action)
        for action in available_actions
        if action.get("action_type") == recommended_type
        and unit["unit_id"] in _target_units(action)
    ]
    alternative_actions = [
        _public_action(action)
        for action in available_actions
        if unit["unit_id"] in _target_units(action)
        and action.get("action_type") != recommended_type
    ]
    return {
        "unit_id": unit["unit_id"],
        "recommended_action_type": recommended_type,
        "recommended_action_id": (
            matching_actions[0].get("action_id") if matching_actions else None
        ),
        "suitability_score": unit["priority_score"],
        "mechanism_basis": mechanisms,
        "candidate_actions": matching_actions,
        "alternative_actions": alternative_actions,
        "evidence_status": (
            "action_mask_supported" if matching_actions else "no_matching_action_in_graph_mdp_mask"
        ),
    }


def _before_after_indicators(
    nodes: list[dict[str, Any]],
    action_sequence: list[dict[str, Any]],
    imagined_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    predicted_delta = {key: 0.0 for key in TARGET_DIRECTIONS}
    for step in imagined_steps:
        dynamics = step.get("predicted_dynamics") or {}
        for key in predicted_delta:
            predicted_delta[key] += _float(dynamics.get(key))
    predicted_delta = {key: round(value, 9) for key, value in predicted_delta.items()}

    initial_by_unit = {
        str(node.get("unit_id") or node.get("node_id")): _normalise_features(
            node.get("features") or node
        )
        for node in nodes
        if node.get("unit_id") is not None or node.get("node_id") is not None
    }
    by_target_unit = _target_unit_before_after(
        initial_by_unit,
        action_sequence,
        imagined_steps,
    )
    return {
        "directions": TARGET_DIRECTIONS,
        "predicted_delta": predicted_delta,
        "direction_check": _direction_check(predicted_delta),
        "target_unit_before_after": by_target_unit,
        "evidence_grade": "learned_world_model_imagined_rollout",
    }


def _target_unit_before_after(
    initial_by_unit: dict[str, dict[str, float]],
    action_sequence: list[dict[str, Any]],
    imagined_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    running = {unit_id: dict(features) for unit_id, features in initial_by_unit.items()}
    rows = []
    for action, step in zip(action_sequence, imagined_steps):
        dynamics = step.get("predicted_dynamics") or {}
        for unit_id in _target_units(action):
            before = dict(running.get(unit_id) or _empty_features())
            after = _apply_dynamics(before, dynamics)
            running[unit_id] = after
            rows.append(
                {
                    "action_id": action.get("action_id"),
                    "action_type": action.get("action_type"),
                    "unit_id": unit_id,
                    "before": {key: round(value, 9) for key, value in before.items()},
                    "after": {key: round(value, 9) for key, value in after.items()},
                    "delta": {
                        key: round(_float(dynamics.get(key)), 9)
                        for key in TARGET_DIRECTIONS
                    },
                }
            )
    return rows


def _equity_conclusion(
    low_units: list[dict[str, Any]],
    before_after_indicators: dict[str, Any],
) -> dict[str, Any]:
    delta = _float(
        (before_after_indicators.get("predicted_delta") or {}).get("equity_delta")
    )
    if delta > 0:
        status = "equity_improves"
    elif delta < 0:
        status = "equity_risk"
    else:
        status = "equity_neutral"
    plan_targets = {
        row.get("unit_id")
        for row in before_after_indicators.get("target_unit_before_after") or []
    }
    low_unit_ids = {unit.get("unit_id") for unit in low_units}
    return {
        "status": status,
        "equity_delta": round(delta, 9),
        "low_livability_units_targeted": sorted(plan_targets & low_unit_ids),
        "low_livability_unit_count": len(low_unit_ids),
        "targeted_low_livability_unit_count": len(plan_targets & low_unit_ids),
        "interpretation": (
            "learned rollout predicts positive equity gain"
            if status == "equity_improves"
            else "learned rollout does not yet predict a positive equity gain"
        ),
    }


def _traditional_method_comparison(
    learned_rollout_report: dict[str, Any],
    synthetic_policy_outcome_benchmark: dict[str, Any],
) -> dict[str, Any]:
    planner = learned_rollout_report.get("learned_rollout_planner") or {}
    selected = planner.get("selected_sequence") or {}
    static = planner.get("static_single_step_baseline") or {}
    one_step = planner.get("one_step_policy_baseline") or {}
    synthetic_comparison = synthetic_policy_outcome_benchmark.get("comparisons") or {}
    return {
        "traditional_baseline": "static_single_step_priority_heuristic",
        "world_model_policy": "multi_step_action_conditioned_learned_rollout",
        "learned_rollout_conservative_reward": round(
            _float(selected.get("imagined_cumulative_conservative_reward")),
            9,
        ),
        "static_single_step_conservative_reward": round(
            _float(static.get("imagined_cumulative_conservative_reward")),
            9,
        ),
        "one_step_policy_conservative_reward": round(
            _float(one_step.get("imagined_cumulative_conservative_reward")),
            9,
        ),
        "learned_rollout_advantage_over_static": round(
            _float(planner.get("imagined_advantage_over_static_single_step")),
            9,
        ),
        "learned_rollout_advantage_over_one_step": round(
            _float(planner.get("imagined_advantage_over_one_step_policy")),
            9,
        ),
        "synthetic_policy_outcome_learned_advantage_over_static": round(
            _float(synthetic_comparison.get("learned_rollout_advantage_over_static")),
            9,
        ),
        "comparison_status": "proxy_and_synthetic_scaffold_only",
    }


def _evidence_boundary(
    search_report: dict[str, Any],
    learned_rollout_report: dict[str, Any],
    synthetic_policy_outcome_benchmark: dict[str, Any],
    tap_like_pm25_scene_manifest: dict[str, Any] | None,
    *,
    supported_claim: str,
    remaining_gates: list[str],
) -> dict[str, Any]:
    tap_like_pm25_scene_manifest = tap_like_pm25_scene_manifest or {}
    return {
        "max_claim_level": "exploratory_only",
        "empirical_superiority_claim": False,
        "supported_claim": supported_claim,
        "evidence_sources": [
            {
                "role": "graph_mdp_and_known_effect_replay",
                "schema": search_report.get("schema"),
                "claim_level": (search_report.get("claim_boundary") or {}).get(
                    "max_claim_level"
                ),
            },
            {
                "role": "learned_action_conditioned_world_model_rollout",
                "schema": learned_rollout_report.get("schema"),
                "claim_level": (learned_rollout_report.get("claim_boundary") or {}).get(
                    "max_claim_level"
                ),
            },
            {
                "role": "synthetic_policy_outcome_scaffold",
                "schema": synthetic_policy_outcome_benchmark.get("schema"),
                "synthetic_status": synthetic_policy_outcome_benchmark.get("synthetic_status"),
                "claim_level": (
                    synthetic_policy_outcome_benchmark.get("claim_boundary") or {}
                ).get("max_claim_level"),
            },
            {
                "role": "tap_like_pm25_scene",
                "schema": tap_like_pm25_scene_manifest.get("schema"),
                "synthetic_status": tap_like_pm25_scene_manifest.get("synthetic_status"),
                "quality_status": tap_like_pm25_scene_manifest.get("quality_status"),
                "claim_level": (
                    tap_like_pm25_scene_manifest.get("claim_boundary") or {}
                ).get("max_claim_level"),
            },
        ],
        "remaining_gates": remaining_gates,
        "not_supported_claims": [
            "observed_policy_outcome_superiority",
            "tap_based_air_pollution_holdout_superiority",
            "causal_policy_effect",
        ],
    }


def _supported_claim(
    learned_rollout_report: dict[str, Any],
    comparison: dict[str, Any],
) -> str:
    reward_mae = _float((learned_rollout_report.get("holdout_metrics") or {}).get("reward_mae"))
    baseline_mae = _float(
        (learned_rollout_report.get("baseline_metrics") or {}).get(
            "train_mean_reward_mae"
        )
    )
    imagined_advantage = _float(comparison.get("learned_rollout_advantage_over_static"))
    synthetic_advantage = _float(
        comparison.get("synthetic_policy_outcome_learned_advantage_over_static")
    )
    if reward_mae < baseline_mae and imagined_advantage > 0 and synthetic_advantage > 0:
        return "business_theory_aligned_learned_rollout_beats_static_proxy_baseline"
    return "no_business_theory_aligned_world_model_advantage_claim_supported"


def _remaining_gates(
    learned_rollout_report: dict[str, Any],
    synthetic_policy_outcome_benchmark: dict[str, Any],
) -> list[str]:
    gates = [
        "observed_policy_outcome_required",
        "tap_or_authoritative_air_quality_required",
        "causal_policy_effect_validation_required",
        "external_observed_holdout_required",
    ]
    gates.extend(learned_rollout_report.get("remaining_gates") or [])
    gates.extend(synthetic_policy_outcome_benchmark.get("remaining_gates") or [])
    return sorted({str(gate) for gate in gates if gate})


def _multi_step_plan(selected_sequence: dict[str, Any]) -> dict[str, Any]:
    action_sequence = [
        _public_action(action)
        for action in selected_sequence.get("action_sequence") or []
    ]
    return {
        "action_count": len(action_sequence),
        "action_sequence": action_sequence,
        "imagined_cumulative_predicted_reward": round(
            _float(selected_sequence.get("imagined_cumulative_predicted_reward")),
            9,
        ),
        "imagined_cumulative_conservative_reward": round(
            _float(selected_sequence.get("imagined_cumulative_conservative_reward")),
            9,
        ),
        "planning_mode": "learned_world_model_multi_step_rollout",
    }


def _dominant_mechanisms(features: dict[str, float]) -> list[str]:
    mechanisms = []
    if features["service_accessibility"] <= 0.5:
        mechanisms.append("service_accessibility_deficit")
    if features["heat_risk"] >= 0.7:
        mechanisms.append("heat_risk_exposure")
    if features["air_pollution_exposure"] >= 0.6:
        mechanisms.append("air_pollution_exposure")
    if features["equity"] >= 0.7 and features["livability"] <= 0.5:
        mechanisms.append("equity_priority")
    if not mechanisms:
        mechanisms.append("multi_factor_livability_gap")
    return mechanisms


def _recommended_action_type(mechanisms: list[str]) -> str:
    for mechanism in mechanisms:
        action_type = MECHANISM_ACTION_PRIORITY.get(mechanism)
        if action_type:
            return action_type
    return "evidence_insufficient"


def _mechanism_summary(mechanism: str) -> str:
    return {
        "service_accessibility_deficit": (
            "low livability is primarily explained by insufficient daily service access"
        ),
        "heat_risk_exposure": (
            "low livability is primarily explained by high urban heat exposure"
        ),
        "air_pollution_exposure": (
            "low livability is primarily explained by high air-pollution exposure"
        ),
        "equity_priority": (
            "low livability overlaps with a high equity-priority or vulnerability signal"
        ),
        "multi_factor_livability_gap": (
            "low livability appears to be driven by multiple moderate deficits"
        ),
    }.get(mechanism, "low livability mechanism is not classified")


def _low_livability_priority_score(features: dict[str, float]) -> float:
    return (
        0.30 * (1.0 - features["livability"])
        + 0.25 * (1.0 - features["service_accessibility"])
        + 0.20 * features["heat_risk"]
        + 0.15 * features["air_pollution_exposure"]
        + 0.10 * features["equity"]
    )


def _direction_check(predicted_delta: dict[str, float]) -> dict[str, bool]:
    return {
        "heat_risk_delta": predicted_delta["heat_risk_delta"] <= 0,
        "air_pollution_exposure_delta": predicted_delta["air_pollution_exposure_delta"] <= 0,
        "service_accessibility_delta": predicted_delta["service_accessibility_delta"] >= 0,
        "equity_delta": predicted_delta["equity_delta"] >= 0,
        "livability_delta": predicted_delta["livability_delta"] >= 0,
    }


def _normalise_features(raw: dict[str, Any]) -> dict[str, float]:
    return {
        "heat_risk": _float(raw.get("heat_risk")),
        "air_pollution_exposure": _float(raw.get("air_pollution_exposure")),
        "service_accessibility": _float(raw.get("service_accessibility")),
        "equity": _float(raw.get("equity")),
        "livability": _float(raw.get("livability")),
    }


def _apply_dynamics(features: dict[str, float], dynamics: dict[str, Any]) -> dict[str, float]:
    return {
        "heat_risk": _clamp01(features["heat_risk"] + _float(dynamics.get("heat_risk_delta"))),
        "air_pollution_exposure": _clamp01(
            features["air_pollution_exposure"]
            + _float(dynamics.get("air_pollution_exposure_delta"))
        ),
        "service_accessibility": _clamp01(
            features["service_accessibility"]
            + _float(dynamics.get("service_accessibility_delta"))
        ),
        "equity": _clamp01(features["equity"] + _float(dynamics.get("equity_delta"))),
        "livability": _clamp01(features["livability"] + _float(dynamics.get("livability_delta"))),
    }


def _public_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action.get("action_id"),
        "action_type": action.get("action_type"),
        "target_units": _target_units(action),
        **(
            {"intensity": action.get("intensity")}
            if action.get("intensity") is not None
            else {}
        ),
        **(
            {"mask_reason": action.get("mask_reason")}
            if action.get("mask_reason") is not None
            else {}
        ),
    }


def _target_units(action: dict[str, Any]) -> list[str]:
    targets = action.get("target_units")
    if isinstance(targets, list) and targets:
        return [str(unit_id) for unit_id in targets]
    if action.get("target_unit") is not None:
        return [str(action.get("target_unit"))]
    return []


def _empty_features() -> dict[str, float]:
    return {
        "heat_risk": 0.0,
        "air_pollution_exposure": 0.0,
        "service_accessibility": 0.0,
        "equity": 0.0,
        "livability": 0.0,
    }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
