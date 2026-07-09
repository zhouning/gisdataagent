"""Full-admin UWM world-model superiority dossier."""

from __future__ import annotations

from typing import Any


UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA = (
    "uwm.full_admin_world_model_superiority_dossier.v1"
)

_SUPPORTED_CLAIM = "bounded_full_admin_world_model_advantage_over_traditional_methods"
_NO_CLAIM = "no_full_admin_world_model_superiority_claim_supported"

_FORBIDDEN_CLAIMS = [
    "observed_policy_outcome_superiority",
    "empirical_policy_superiority",
    "causal_effect_identification_from_current_proxy_scene",
    "authoritative_governance_deployment_readiness",
]


def build_uwm_full_admin_world_model_superiority_dossier(
    *,
    dossier_id: str,
    created_at: str,
    full_admin_graph_planner_replay: dict[str, Any],
    full_admin_graph_drl_training_report: dict[str, Any],
    full_admin_learned_world_model_rollout: dict[str, Any],
    full_admin_energy_regularized_planner_report: dict[str, Any],
    full_admin_livability_decision_package: dict[str, Any],
    livability_endpoint_suite: dict[str, Any],
    full_admin_service_accessibility_surface: dict[str, Any],
    geographic_similarity_kernel: dict[str, Any],
    spatial_causal_question_registry: dict[str, Any],
    production_governance_planner_binding_gate: dict[str, Any],
    source_artifact_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a claim-safe superiority dossier over real full-admin artifacts."""

    _require_dicts(
        {
            "full_admin_graph_planner_replay": full_admin_graph_planner_replay,
            "full_admin_graph_drl_training_report": (
                full_admin_graph_drl_training_report
            ),
            "full_admin_learned_world_model_rollout": (
                full_admin_learned_world_model_rollout
            ),
            "full_admin_energy_regularized_planner_report": (
                full_admin_energy_regularized_planner_report
            ),
            "full_admin_livability_decision_package": (
                full_admin_livability_decision_package
            ),
            "livability_endpoint_suite": livability_endpoint_suite,
            "full_admin_service_accessibility_surface": (
                full_admin_service_accessibility_surface
            ),
            "geographic_similarity_kernel": geographic_similarity_kernel,
            "spatial_causal_question_registry": spatial_causal_question_registry,
            "production_governance_planner_binding_gate": (
                production_governance_planner_binding_gate
            ),
        }
    )
    scope_guard = _full_admin_scope_guard(
        full_admin_graph_planner_replay,
        full_admin_graph_drl_training_report,
        full_admin_learned_world_model_rollout,
        full_admin_energy_regularized_planner_report,
        full_admin_service_accessibility_surface,
        geographic_similarity_kernel,
    )
    endpoint_matrix = _endpoint_superiority_matrix(livability_endpoint_suite)
    world_matrix = _world_model_system_matrix(
        full_admin_graph_planner_replay,
        full_admin_graph_drl_training_report,
        full_admin_learned_world_model_rollout,
        full_admin_energy_regularized_planner_report,
        full_admin_livability_decision_package,
        livability_endpoint_suite,
    )
    baseline_matrix = _traditional_baseline_matrix(
        full_admin_graph_planner_replay,
        full_admin_graph_drl_training_report,
        full_admin_learned_world_model_rollout,
        full_admin_energy_regularized_planner_report,
        livability_endpoint_suite,
    )
    causal_gate = _causal_and_governance_gate(
        full_admin_graph_planner_replay,
        full_admin_livability_decision_package,
        spatial_causal_question_registry,
        production_governance_planner_binding_gate,
    )
    ready = (
        scope_guard["passed"] is True
        and endpoint_matrix["endpoint_suite_ready"] is True
        and world_matrix["all_required_world_model_advantages_positive"] is True
        and causal_gate["causal_governance_gate_ready_for_bounded_claim"] is True
    )
    remaining_gates = _remaining_gates(
        scope_guard=scope_guard,
        endpoint_matrix=endpoint_matrix,
        world_matrix=world_matrix,
        causal_gate=causal_gate,
    )
    return {
        "schema": UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA,
        "dossier_id": dossier_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "full_admin_scope_guard": scope_guard,
        "traditional_baseline_matrix": baseline_matrix,
        "world_model_system_matrix": world_matrix,
        "endpoint_superiority_matrix": endpoint_matrix,
        "causal_and_governance_gate": causal_gate,
        "claim_ladder": _claim_ladder(ready),
        "supported_claim": _SUPPORTED_CLAIM if ready else _NO_CLAIM,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "Full-admin dossier aggregates real prepared renderer, Graph-MDP, "
                "simulator, planner, learned value/rollout, endpoint and governance "
                "evidence. It supports bounded same-scene world-model advantage over "
                "traditional methods, not observed policy-outcome superiority."
            ),
        },
        "forbidden_claims": list(_FORBIDDEN_CLAIMS),
        "remaining_gates": remaining_gates,
        "audit_trace": _audit_trace(source_artifact_paths or {}),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_uwm_full_admin_world_model_superiority_dossier(
    dossier: dict[str, Any],
) -> dict[str, Any]:
    """Validate the dossier contract without requiring the claim to be supported."""

    errors: list[str] = []
    if not isinstance(dossier, dict):
        return {"valid": False, "errors": ["dossier must be a dictionary"]}
    if dossier.get("schema") != UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA:
        errors.append(
            "schema must be uwm.full_admin_world_model_superiority_dossier.v1"
        )
    if dossier.get("experiment_scope") != "full_admin_graph":
        errors.append("experiment_scope must be full_admin_graph")
    if dossier.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must be false")
    if dossier.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must be false")
    forbidden = set(dossier.get("forbidden_claims") or [])
    for claim in _FORBIDDEN_CLAIMS:
        if claim not in forbidden:
            errors.append(f"forbidden_claims missing {claim}")
    supported = dossier.get("supported_claim")
    if supported == _SUPPORTED_CLAIM:
        if (dossier.get("full_admin_scope_guard") or {}).get("passed") is not True:
            errors.append("supported claim requires full_admin_scope_guard.passed")
        if (
            (dossier.get("endpoint_superiority_matrix") or {}).get(
                "endpoint_suite_ready"
            )
            is not True
        ):
            errors.append("supported claim requires endpoint suite readiness")
        if (
            (dossier.get("world_model_system_matrix") or {}).get(
                "all_required_world_model_advantages_positive"
            )
            is not True
        ):
            errors.append("supported claim requires positive world-model advantages")
        if (
            (dossier.get("causal_and_governance_gate") or {}).get(
                "causal_governance_gate_ready_for_bounded_claim"
            )
            is not True
        ):
            errors.append("supported claim requires causal governance gate")
    elif supported != _NO_CLAIM:
        errors.append("supported_claim has unknown value")
    return {"valid": not errors, "errors": errors}


def _full_admin_scope_guard(
    planner: dict[str, Any],
    graph_dqn: dict[str, Any],
    learned_rollout: dict[str, Any],
    energy_planner: dict[str, Any],
    service_surface: dict[str, Any],
    geographic_similarity_kernel: dict[str, Any],
) -> dict[str, Any]:
    planner_graph = (
        (planner.get("graph_mdp_state") or {}).get("graph_statistics") or {}
    )
    planner_guard = planner.get("full_data_guard") or {}
    graph_training = graph_dqn.get("training_summary") or {}
    learned_training = learned_rollout.get("training_summary") or {}
    energy_guard = energy_planner.get("full_data_guard") or {}
    service_counts = service_surface.get("source_feature_counts") or {}
    service_coverage = service_surface.get("coverage") or {}
    similarity_summary = geographic_similarity_kernel.get("summary") or {}
    values = {
        "graph_node_count": _int(planner_graph.get("node_count")),
        "graph_edge_count": _int(planner_graph.get("edge_count")),
        "admin_boundary_edge_count": _int(
            planner_guard.get("source_admin_boundary_edge_count")
        ),
        "geographic_similarity_edge_count": _int(
            similarity_summary.get("similarity_edge_count")
        ),
        "available_action_count": _int(planner_graph.get("available_action_count")),
        "transition_count": _int(
            (planner.get("trajectory_dataset") or {}).get("transition_count")
        ),
        "service_surface_admin_unit_count": _int(
            service_surface.get("admin_unit_count")
        ),
        "local_poi_point_count": _int(service_counts.get("poi_points")),
        "local_road_count": _int(service_counts.get("roads")),
        "service_missing_admin_count": _int(
            service_coverage.get("service_missing_admin_count")
        ),
    }
    required = {
        "graph_node_count": 1017,
        "graph_edge_count": 7932,
        "admin_boundary_edge_count": 2847,
        "geographic_similarity_edge_count": 5085,
        "available_action_count": 1137,
        "transition_count": 6817,
        "service_surface_admin_unit_count": 1017,
        "local_poi_point_count": 1194351,
        "local_road_count": 50366,
        "service_missing_admin_count": 0,
    }
    mismatches = [
        {"metric": key, "expected": expected, "observed": values[key]}
        for key, expected in required.items()
        if values[key] != expected
    ]
    passed = (
        not mismatches
        and planner.get("experiment_scope") == "full_admin_graph"
        and graph_dqn.get("experiment_scope") == "full_admin_graph"
        and learned_rollout.get("experiment_scope") == "full_admin_graph"
        and energy_planner.get("experiment_scope") == "full_admin_graph"
        and service_surface.get("experiment_scope") == "full_admin_graph"
        and planner_guard.get("passed") is True
        and (learned_rollout.get("full_data_guard") or {}).get("passed") is True
        and energy_guard.get("passed") is True
        and _int(graph_training.get("real_data_graph_node_count")) == 1017
        and _int(graph_training.get("real_data_available_action_count")) == 1137
        and _int(learned_training.get("source_graph_node_count")) == 1017
        and _int(learned_training.get("source_available_action_count")) == 1137
        and _int(energy_guard.get("available_action_count")) == 1137
    )
    return {
        "passed": passed,
        "required_scope": "full_admin_graph",
        **values,
        "mismatches": mismatches,
    }


def _traditional_baseline_matrix(
    planner: dict[str, Any],
    graph_dqn: dict[str, Any],
    learned_rollout: dict[str, Any],
    energy_planner: dict[str, Any],
    endpoint_suite: dict[str, Any],
) -> dict[str, Any]:
    endpoint_baselines = [
        {
            "endpoint_id": endpoint.get("endpoint_id"),
            "best_traditional_baseline": endpoint.get("best_traditional_baseline"),
            "best_traditional_baseline_mae": _float(
                endpoint.get("best_traditional_baseline_mae")
            ),
            "uwm_mae": _float(endpoint.get("uwm_mae")),
        }
        for endpoint in endpoint_suite.get("endpoint_evaluations") or []
    ]
    families = {
        "final_endpoint_best_traditional_baselines": endpoint_baselines,
        "same_scene_static_heuristic": {
            "static_single_step_reward": _float(
                (planner.get("static_single_step_baseline") or {}).get(
                    "cumulative_reward"
                )
            ),
        },
        "traditional_static_graph_mdp_policy": {
            "traditional_static_cumulative_reward": _float(
                (graph_dqn.get("baseline_evaluation") or {}).get(
                    "traditional_static_cumulative_reward"
                )
            ),
        },
        "learned_rollout_static_and_one_step_baselines": {
            "imagined_advantage_over_static_single_step": _float(
                (learned_rollout.get("learned_rollout_planner") or {}).get(
                    "imagined_advantage_over_static_single_step"
                )
            ),
            "imagined_advantage_over_one_step_policy": _float(
                (learned_rollout.get("learned_rollout_planner") or {}).get(
                    "imagined_advantage_over_one_step_policy"
                )
            ),
        },
        "energy_regularized_traditional_static": {
            "advantage_over_traditional_static": _float(
                (energy_planner.get("selected_sequence") or {}).get(
                    "advantage_over_traditional_static"
                )
            ),
        },
    }
    return {
        "baseline_family_count": len(families),
        "baseline_families": families,
    }


def _world_model_system_matrix(
    planner: dict[str, Any],
    graph_dqn: dict[str, Any],
    learned_rollout: dict[str, Any],
    energy_planner: dict[str, Any],
    decision_package: dict[str, Any],
    endpoint_suite: dict[str, Any],
) -> dict[str, Any]:
    risk = planner.get("risk_adjusted_planner_evaluation") or {}
    graph_learned = graph_dqn.get("learned_policy_evaluation") or {}
    learned_planner = learned_rollout.get("learned_rollout_planner") or {}
    energy_selected = energy_planner.get("selected_sequence") or {}
    components = {
        "planner_replay": {
            "ready": (
                planner.get("experiment_scope") == "full_admin_graph"
                and (planner.get("claim_boundary") or {}).get("max_claim_level")
                == "bounded_support"
            ),
            "advantage_over_static": _float(
                planner.get("advantage_over_static_single_step")
            ),
            "observed_policy_outcome_superiority_claim": False,
        },
        "risk_adjusted_planner": {
            "ready": risk.get("risk_calibrated_planner_replay_ready") is True,
            "advantage_over_static": _float(
                risk.get("risk_adjusted_advantage_over_static_single_step")
            ),
            "observed_policy_outcome_superiority_claim": False,
        },
        "graph_dqn": {
            "ready": graph_dqn.get("experiment_scope") == "full_admin_graph",
            "advantage_over_traditional_static": _float(
                graph_learned.get("advantage_over_traditional_static")
            ),
            "observed_policy_outcome_superiority_claim": False,
        },
        "learned_rollout_static": {
            "ready": learned_rollout.get("experiment_scope") == "full_admin_graph",
            "advantage_over_static": _float(
                learned_planner.get("imagined_advantage_over_static_single_step")
            ),
            "observed_policy_outcome_superiority_claim": False,
        },
        "learned_rollout_one_step": {
            "ready": learned_rollout.get("experiment_scope") == "full_admin_graph",
            "advantage_over_one_step_policy": _float(
                learned_planner.get("imagined_advantage_over_one_step_policy")
            ),
            "observed_policy_outcome_superiority_claim": False,
        },
        "energy_regularized_planner": {
            "ready": (
                energy_planner.get("full_admin_energy_regularized_planner_ready")
                is True
            ),
            "advantage_over_traditional_static": _float(
                energy_selected.get("advantage_over_traditional_static")
            ),
            "observed_policy_outcome_superiority_claim": False,
        },
        "full_admin_decision_package": {
            "ready": (
                decision_package.get("full_admin_decision_package_ready") is True
            ),
            "supported_claim": decision_package.get("supported_claim"),
            "observed_policy_outcome_superiority_claim": False,
        },
        "final_endpoint_suite": {
            "ready": (
                endpoint_suite.get("all_endpoints_beat_traditional_baselines") is True
            ),
            "supported_claim": endpoint_suite.get("supported_claim"),
            "observed_policy_outcome_superiority_claim": False,
        },
    }
    required_positive = [
        components["planner_replay"]["advantage_over_static"],
        components["risk_adjusted_planner"]["advantage_over_static"],
        components["graph_dqn"]["advantage_over_traditional_static"],
        components["learned_rollout_static"]["advantage_over_static"],
        components["learned_rollout_one_step"]["advantage_over_one_step_policy"],
        components["energy_regularized_planner"]["advantage_over_traditional_static"],
    ]
    return {
        "components": components,
        "all_required_world_model_advantages_positive": all(
            value > 0.0 for value in required_positive
        )
        and all(component.get("ready") is True for component in components.values()),
    }


def _endpoint_superiority_matrix(endpoint_suite: dict[str, Any]) -> dict[str, Any]:
    rows = [
        {
            "endpoint_id": endpoint.get("endpoint_id"),
            "domain": endpoint.get("domain"),
            "uwm_model": endpoint.get("uwm_model"),
            "uwm_mae": _float(endpoint.get("uwm_mae")),
            "best_traditional_baseline": endpoint.get("best_traditional_baseline"),
            "best_traditional_baseline_mae": _float(
                endpoint.get("best_traditional_baseline_mae")
            ),
            "relative_mae_reduction_vs_best_traditional": _float(
                endpoint.get("relative_mae_reduction_vs_best_traditional")
            ),
            "beats_traditional_baselines": bool(
                endpoint.get("beats_traditional_baselines")
            ),
            "policy_outcome_claim": bool(endpoint.get("policy_outcome_claim")),
        }
        for endpoint in endpoint_suite.get("endpoint_evaluations") or []
    ]
    all_ready = (
        endpoint_suite.get("schema") == "uwm.livability_endpoint_suite.v1"
        and _int(endpoint_suite.get("endpoint_count")) >= 3
        and _int(endpoint_suite.get("endpoint_count")) == len(rows)
        and _int(endpoint_suite.get("ready_endpoint_count")) == len(rows)
        and bool(rows)
        and all(row["beats_traditional_baselines"] is True for row in rows)
        and all(row["policy_outcome_claim"] is False for row in rows)
        and _float(
            endpoint_suite.get("mean_relative_mae_reduction_vs_best_traditional")
        )
        > 0.0
        and _float(
            endpoint_suite.get("min_relative_mae_reduction_vs_best_traditional")
        )
        > 0.0
    )
    return {
        "endpoint_suite_ready": all_ready,
        "endpoint_count": _int(endpoint_suite.get("endpoint_count")),
        "ready_endpoint_count": _int(endpoint_suite.get("ready_endpoint_count")),
        "all_endpoints_beat_best_traditional": all(
            row["beats_traditional_baselines"] is True for row in rows
        ),
        "mean_relative_mae_reduction_vs_best_traditional": _float(
            endpoint_suite.get("mean_relative_mae_reduction_vs_best_traditional")
        ),
        "min_relative_mae_reduction_vs_best_traditional": _float(
            endpoint_suite.get("min_relative_mae_reduction_vs_best_traditional")
        ),
        "endpoint_rows": rows,
        "observed_policy_outcome_superiority_claim": False,
    }


def _causal_and_governance_gate(
    planner: dict[str, Any],
    decision_package: dict[str, Any],
    spatial_causal_question_registry: dict[str, Any],
    governance_gate: dict[str, Any],
) -> dict[str, Any]:
    planner_binding = planner.get("spatial_causal_contract_binding") or {}
    final_binding = decision_package.get("spatial_causal_contract_binding") or {}
    governance_summary = governance_gate.get("summary") or {}
    planner_ready = (
        planner_binding.get("binding_ready") is True
        and _int(planner_binding.get("feasible_action_count")) == 1137
        and _int(planner_binding.get("attached_action_count")) == 1137
        and _int(planner_binding.get("missing_contract_action_count")) == 0
        and _int(planner_binding.get("policy_outcome_claim_allowed_action_count"))
        == 0
    )
    final_ready = (
        final_binding.get("binding_ready") is True
        and _int(final_binding.get("recommended_action_count"))
        == _int(final_binding.get("attached_action_count"))
        and _int(final_binding.get("missing_contract_action_count")) == 0
        and _int(final_binding.get("policy_outcome_claim_allowed_action_count")) == 0
    )
    governance_ready = (
        governance_gate.get("schema")
        == "uwm.production_governance_planner_binding_gate.v1"
        and governance_gate.get("experiment_scope") == "full_admin_graph"
        and governance_gate.get("binding_gate_ready") is True
        and _int(governance_summary.get("required_gate_count")) == 9
    )
    return {
        "causal_governance_gate_ready_for_bounded_claim": (
            planner_ready
            and final_ready
            and governance_ready
            and spatial_causal_question_registry.get("registry_ready") is True
        ),
        "spatial_causal_registry_ready": (
            spatial_causal_question_registry.get("registry_ready") is True
        ),
        "planner_candidate_causal_binding_ready": planner_ready,
        "planner_feasible_action_count": _int(
            planner_binding.get("feasible_action_count")
        ),
        "planner_attached_action_count": _int(
            planner_binding.get("attached_action_count")
        ),
        "planner_missing_contract_action_count": _int(
            planner_binding.get("missing_contract_action_count")
        ),
        "planner_underidentified_policy_effect_action_count": _int(
            planner_binding.get("underidentified_policy_effect_action_count")
        ),
        "planner_policy_outcome_claim_allowed_action_count": _int(
            planner_binding.get("policy_outcome_claim_allowed_action_count")
        ),
        "final_output_causal_binding_ready": final_ready,
        "final_recommended_action_count": _int(
            final_binding.get("recommended_action_count")
        ),
        "final_attached_action_count": _int(final_binding.get("attached_action_count")),
        "production_governance_gate_ready": governance_ready,
        "authoritative_governance_data_closure_ready": bool(
            governance_gate.get("authoritative_governance_data_closure_ready")
        ),
        "production_planner_governance_binding_ready": bool(
            governance_gate.get("planner_governance_binding_ready")
        ),
        "production_deployment_ready": bool(
            governance_gate.get("authoritative_governance_data_closure_ready")
        )
        and bool(governance_gate.get("planner_governance_binding_ready")),
        "missing_authoritative_table_count": _int(
            governance_summary.get("missing_table_count")
        ),
        "accepted_authoritative_row_count": _int(
            governance_summary.get("accepted_authoritative_row_count")
        ),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _claim_ladder(ready: bool) -> list[dict[str, Any]]:
    return [
        {
            "claim": _SUPPORTED_CLAIM,
            "scope": "full_admin_graph_same_scene",
            "claim_level": "bounded_support" if ready else "not_for_claim",
            "allowed_in_report": ready,
            "policy_outcome_claim": False,
            "spatial_attribution_claim": False,
        }
    ]


def _remaining_gates(
    *,
    scope_guard: dict[str, Any],
    endpoint_matrix: dict[str, Any],
    world_matrix: dict[str, Any],
    causal_gate: dict[str, Any],
) -> list[str]:
    gates = [
        "observed_policy_outcome_holdout_required",
        "off_policy_evaluation_on_real_intervention_logs_required",
        "causal_policy_effect_validation_required",
        "authoritative_governance_data_closure_required",
    ]
    if scope_guard.get("passed") is not True:
        gates.append("full_admin_scope_guard_failed")
    if endpoint_matrix.get("endpoint_suite_ready") is not True:
        gates.append("endpoint_superiority_matrix_failed")
    if world_matrix.get("all_required_world_model_advantages_positive") is not True:
        gates.append("world_model_system_matrix_failed")
    if causal_gate.get("causal_governance_gate_ready_for_bounded_claim") is not True:
        gates.append("causal_and_governance_gate_failed")
    if causal_gate.get("production_deployment_ready") is not True:
        gates.append("production_deployment_readiness_blocked")
    return gates


def _audit_trace(source_artifact_paths: dict[str, str]) -> dict[str, Any]:
    return {
        "source_artifact_paths": dict(sorted(source_artifact_paths.items())),
        "artifact_path_policy": "local_prepared_full_admin_artifacts_no_network_download",
        "data_claim_policy": (
            "bounded same-scene world-model superiority only; observed policy "
            "outcome superiority remains forbidden"
        ),
    }


def _require_dicts(payloads: dict[str, Any]) -> None:
    for name, payload in payloads.items():
        if not isinstance(payload, dict):
            raise TypeError(f"{name} must be a dictionary")


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return round(float(value), 9)
    except (TypeError, ValueError):
        return default
