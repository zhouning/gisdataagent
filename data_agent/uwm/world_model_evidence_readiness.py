"""Claim-safe UWM world-model evidence readiness summaries."""

from __future__ import annotations

from typing import Any


UWM_WORLD_MODEL_EVIDENCE_READINESS_SCHEMA = "uwm.world_model_evidence_readiness.v1"


def build_world_model_evidence_readiness(
    data_foundation_evidence_gate: dict[str, Any],
) -> dict[str, Any]:
    """Build a world-model claim ladder from the data-foundation evidence gate."""

    evidence_slices = data_foundation_evidence_gate.get("evidence_slices") or {}
    openaq = evidence_slices.get("openaq_observed_temporal_state") or {}
    tap = evidence_slices.get("tap_external_temporal_transition") or {}
    rollout = evidence_slices.get("learned_world_model_rollout") or {}
    intervention = evidence_slices.get("livability_intervention_package") or {}
    admin_graph = evidence_slices.get("admin_spatial_adjacency_graph") or {}
    local_foundation = evidence_slices.get("local_planning_data_foundation") or {}

    claim_ladder = _claim_ladder(data_foundation_evidence_gate)
    forbidden_claims = _forbidden_claims(data_foundation_evidence_gate, tap)
    traditional_ready = (
        bool(data_foundation_evidence_gate.get("observed_state_prediction_superiority_claim"))
        and bool(data_foundation_evidence_gate.get("external_temporal_transition_superiority_claim"))
    )
    policy_ready = bool(data_foundation_evidence_gate.get("observed_policy_outcome_superiority_claim"))
    empirical_claim = bool(data_foundation_evidence_gate.get("empirical_superiority_claim"))

    return {
        "schema": UWM_WORLD_MODEL_EVIDENCE_READINESS_SCHEMA,
        "overall_claim_ceiling": _overall_claim_ceiling(claim_ladder),
        "system_level_superiority_summary": _system_level_superiority_summary(
            traditional_ready=traditional_ready,
            policy_ready=policy_ready,
            empirical_claim=empirical_claim,
        ),
        "traditional_method_comparison_ready": traditional_ready,
        "policy_outcome_superiority_ready": policy_ready,
        "empirical_superiority_claim": empirical_claim,
        "architecture_evidence": {
            "renderer": _renderer_evidence(local_foundation, admin_graph),
            "simulator": _simulator_evidence(openaq, tap, rollout),
            "planner": _planner_evidence(rollout, intervention),
            "policy_outcome_evaluator": _policy_outcome_evaluator_evidence(
                data_foundation_evidence_gate
            ),
        },
        "claim_ladder": claim_ladder,
        "forbidden_claims": forbidden_claims,
        "remaining_gates": list(data_foundation_evidence_gate.get("remaining_gates") or []),
        "next_actions": _next_actions(data_foundation_evidence_gate),
    }


def _claim_ladder(gate: dict[str, Any]) -> list[dict[str, Any]]:
    ladder = []
    for claim in gate.get("supported_claims") or []:
        claim_level = str(claim.get("claim_level") or "not_for_claim")
        policy_outcome_claim = bool(claim.get("policy_outcome_claim"))
        ladder.append(
            {
                "claim": claim.get("claim"),
                "scope": claim.get("scope"),
                "claim_level": claim_level,
                "allowed_in_report": claim_level == "bounded_support" and not policy_outcome_claim,
                "policy_outcome_claim": policy_outcome_claim,
                "spatial_attribution_claim": bool(claim.get("spatial_attribution_claim")),
            }
        )
    return ladder


def _overall_claim_ceiling(claim_ladder: list[dict[str, Any]]) -> str:
    if any(claim.get("claim_level") == "bounded_support" for claim in claim_ladder):
        return "bounded_support"
    if any(claim.get("claim_level") == "exploratory_only" for claim in claim_ladder):
        return "exploratory_only"
    if any(claim.get("claim_level") == "fragile" for claim in claim_ladder):
        return "fragile"
    return "not_for_claim"


def _system_level_superiority_summary(
    *,
    traditional_ready: bool,
    policy_ready: bool,
    empirical_claim: bool,
) -> str:
    if traditional_ready and policy_ready and empirical_claim:
        return "observed_policy_outcome_superiority_ready"
    if traditional_ready:
        return "bounded_state_prediction_and_transition_advantage_without_policy_outcome_superiority"
    return "no_system_level_superiority_claim_supported"


def _renderer_evidence(local_foundation: dict[str, Any], admin_graph: dict[str, Any]) -> dict[str, Any]:
    local_ready = bool(local_foundation.get("source_artifact_exists"))
    graph_ready = bool(admin_graph.get("source_artifact_exists")) and _safe_int(
        admin_graph.get("node_count")
    ) > 0
    return {
        "ready": local_ready and graph_ready,
        "evidence": [
            "prepared_local_planning_data_foundation" if local_ready else "local_foundation_missing",
            "admin_spatial_adjacency_graph" if graph_ready else "admin_spatial_graph_missing",
        ],
        "claim_level": _min_claim_level(
            [
                str(local_foundation.get("claim_level") or "not_for_claim"),
                str(admin_graph.get("claim_level") or "not_for_claim"),
            ]
        ),
    }


def _simulator_evidence(
    openaq: dict[str, Any],
    tap: dict[str, Any],
    rollout: dict[str, Any],
) -> dict[str, Any]:
    observed_temporal_ready = (
        bool(openaq.get("source_artifact_exists"))
        and str(openaq.get("claim_level")) == "bounded_support"
        and _safe_float(openaq.get("overall_holdout_win_rate")) > 0.5
        and bool(openaq.get("temporal_order_negative_control_passed"))
    )
    external_transition_ready = (
        bool(tap.get("source_artifact_exists"))
        and str(tap.get("claim_level")) == "bounded_support"
        and _safe_float(tap.get("best_transition_mae"))
        < _safe_float(tap.get("best_non_spatial_dynamic_mae"), default=float("inf"))
        and _safe_float(tap.get("paired_win_rate_vs_best_non_spatial_dynamic")) > 0.5
        and bool(tap.get("temporal_order_negative_control_passed"))
        and bool(tap.get("future_label_leakage_guard_passed"))
        and tap.get("spatial_negative_control_passed") is False
    )
    learned_rollout_ready = (
        bool(rollout.get("source_artifact_exists"))
        and str(rollout.get("claim_level")) == "bounded_support"
        and _safe_float(rollout.get("holdout_reward_mae"), default=float("inf"))
        < _safe_float(rollout.get("train_mean_reward_mae"), default=0.0)
    )
    return {
        "ready": observed_temporal_ready and external_transition_ready and learned_rollout_ready,
        "observed_temporal_state_ready": observed_temporal_ready,
        "external_temporal_transition_ready": external_transition_ready,
        "learned_rollout_ready": learned_rollout_ready,
        "spatial_attribution_ready": False,
        "claim_level": "bounded_support"
        if observed_temporal_ready and external_transition_ready and learned_rollout_ready
        else "not_for_claim",
    }


def _planner_evidence(rollout: dict[str, Any], intervention: dict[str, Any]) -> dict[str, Any]:
    rollout_advantage_ready = (
        bool(rollout.get("source_artifact_exists"))
        and _safe_float(rollout.get("imagined_advantage_over_static")) > 0.0
        and _safe_float(rollout.get("imagined_advantage_over_one_step")) > 0.0
    )
    intervention_ready = (
        bool(intervention.get("source_artifact_exists"))
        and str(intervention.get("claim_level")) == "exploratory_only"
        and bool(intervention.get("predicted_delta"))
    )
    return {
        "ready": rollout_advantage_ready and intervention_ready,
        "learned_rollout_planner_ready": rollout_advantage_ready,
        "livability_intervention_package_ready": intervention_ready,
        "claim_level": "exploratory_only" if intervention_ready else "not_for_claim",
        "policy_outcome_claim": False,
    }


def _policy_outcome_evaluator_evidence(gate: dict[str, Any]) -> dict[str, Any]:
    remaining_gates = list(gate.get("remaining_gates") or [])
    ready = bool(gate.get("observed_policy_outcome_superiority_claim"))
    return {
        "ready": ready,
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "remaining_gates": remaining_gates,
        "policy_outcome_claim": ready,
    }


def _forbidden_claims(gate: dict[str, Any], tap: dict[str, Any]) -> list[str]:
    claims = []
    if not gate.get("observed_policy_outcome_superiority_claim"):
        claims.append("observed_policy_outcome_superiority")
    if tap.get("spatial_negative_control_passed") is False:
        claims.append("spatial_attribution_for_tap_external_transition")
    if not gate.get("empirical_superiority_claim"):
        claims.append("overall_empirical_policy_superiority")
    return claims


def _next_actions(gate: dict[str, Any]) -> list[str]:
    actions = ["complete_world_model_evidence_readiness_section"]
    remaining_gates = set(gate.get("remaining_gates") or [])
    if "observed_policy_outcome_required" in remaining_gates:
        actions.append("collect_observed_policy_outcome_validation_data")
    if "scene_aligned_station_calibrated_air_quality_holdout_required" in remaining_gates:
        actions.append("build_scene_aligned_station_calibrated_air_quality_holdout")
    if "causal_policy_effect_validation_required" in remaining_gates:
        actions.append("design_causal_policy_effect_validation")
    return actions


def _min_claim_level(levels: list[str]) -> str:
    order = {
        "bounded_support": 3,
        "exploratory_only": 2,
        "fragile": 1,
        "not_for_claim": 0,
    }
    if not levels:
        return "not_for_claim"
    return min(levels, key=lambda level: order.get(level, 0))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
