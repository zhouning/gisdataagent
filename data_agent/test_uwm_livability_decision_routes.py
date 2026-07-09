from data_agent.api import uwm_livability_decision_routes as routes


def _route_methods(route_list, path):
    for route in route_list:
        if route.path == path:
            return set(route.methods or [])
    return set()


def test_livability_decision_routes_are_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes

    route_list = routes.get_uwm_livability_decision_routes()
    frontend_route_list = get_frontend_api_routes()

    assert "GET" in _route_methods(route_list, "/api/uwm/livability-decision")
    assert "GET" in _route_methods(frontend_route_list, "/api/uwm/livability-decision")


def test_livability_decision_payload_uses_real_same_data_world_model_artifacts():
    payload = routes.load_uwm_livability_decision_payload()

    assert payload["schema"] == routes.UWM_LIVABILITY_DECISION_API_SCHEMA
    assert payload["world_model_components_used"] == [
        "renderer",
        "simulator",
        "planner",
    ]
    assert payload["shared_data_contract"] == {
        "scene_id": "uwm-multisource-livability-scene-2026-07-06",
        "admin_unit_count": 36,
        "same_data_basis": True,
        "same_livability_scenario": True,
    }

    decision = payload["decision_package"]
    comparison = decision["comparison_against_traditional_static_heuristic"]
    replay = decision["replay_baseline_suite"]
    spatial_kernel = decision["spatial_spillover_kernel_evidence"]
    rl_training = decision["rl_training_evidence"]
    graph_drl = decision["graph_drl_training_evidence"]

    assert decision["decision_package_ready"] is True
    assert decision["action_portfolio"]["target_units"] == [
        "江北区|观音桥街道|653",
        "九龙坡区|九龙镇|77",
    ]
    assert comparison["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert comparison["risk_adjusted_advantage_over_static"] == 0.012777213
    assert comparison["neighbor_livability_delta_advantage"] == 0.272680076
    assert replay["single_action_transition_count"] == 355
    assert replay["empirical_one_sided_p_value"] == 0.002809
    assert spatial_kernel["ready"] is True
    assert spatial_kernel["directional_edge_count"] == 227
    assert spatial_kernel["uses_shared_boundary_length"] is True
    assert spatial_kernel["uses_admin_livability_need"] is True
    assert rl_training["ready"] is True
    assert rl_training["algorithm"] == "dyna_q_tabular_model_based_rl"
    assert rl_training["episode_count"] == 160
    assert rl_training["advantage_over_traditional_static"] > 0
    assert graph_drl["ready"] is True
    assert graph_drl["algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert graph_drl["is_deep_rl"] is True
    assert graph_drl["uses_graph_message_passing"] is True
    assert graph_drl["policy_or_value_network_trained"] is True
    assert graph_drl["training_sample_count"] == 3600
    assert graph_drl["advantage_over_traditional_static"] > 0
    assert graph_drl["observed_policy_outcome_superiority_claim"] is False

    demo = payload["comparison_demo"]
    assert demo["demo_ready"] is True
    assert demo["traditional_method_output"]["final_output_type"] == (
        "static_problem_ranking"
    )
    assert demo["uwm_output"]["final_output_type"] == (
        "counterfactual_decision_package"
    )
    assert "multi_step_action_sequence" in demo["capability_delta"]["uwm_only_outputs"]
    assert "counterfactual_state_delta" in demo["capability_delta"]["uwm_only_outputs"]
    assert "trained_graph_drl_value_network_evidence" in demo["capability_delta"]["uwm_only_outputs"]
    assert payload["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert payload["observed_policy_outcome_superiority_claim"] is False
    assert payload["empirical_superiority_claim"] is False


def test_livability_decision_payload_exposes_full_admin_governance_binding_gate():
    payload = routes.load_uwm_livability_decision_payload()

    full_admin = payload["full_admin_decision_package"]
    governance = payload["production_governance_binding_evidence"]

    assert full_admin["schema"] == "uwm.full_admin_livability_decision_package.v1"
    assert full_admin["full_admin_decision_package_ready"] is True
    assert full_admin["full_data_guard"]["graph_node_count"] == 1017
    assert full_admin["full_data_guard"]["graph_edge_count"] == 7932
    assert full_admin["full_data_guard"]["available_action_count"] == 1137
    assert full_admin["source_schemas"]["production_governance_planner_binding_gate"] == (
        "uwm.production_governance_planner_binding_gate.v1"
    )
    assert governance == full_admin["production_governance_binding_evidence"]
    assert governance["production_governance_binding_gate_ready"] is True
    assert governance["planner_governance_binding_ready"] is False
    assert governance["production_planner_binding_blocked"] is True
    assert governance["blocking_gate_count"] == 7
    assert governance["missing_table_count"] == 5
    assert governance["accepted_authoritative_row_count"] == 0
    assert payload["planner_governance_binding_ready"] is False
    assert payload["active_decision_package_scope"] == "full_admin_graph"
    assert payload["observed_policy_outcome_superiority_claim"] is False
    assert payload["empirical_superiority_claim"] is False


def test_livability_decision_payload_exposes_spatial_causal_question_registry():
    payload = routes.load_uwm_livability_decision_payload()

    registry = payload["spatial_causal_question_registry_evidence"]
    readiness = payload["world_model_evidence_readiness"]
    spatial_readiness = readiness["architecture_evidence"]["spatial_causal_questions"]

    assert registry["spatial_causal_question_registry_ready"] is True
    assert registry["active_causal_question_count"] == 3
    assert registry["currently_bound_feasible_action_count"] == 1137
    assert registry["underidentified_policy_effect_question_count"] == 3
    assert registry["identified_policy_effect_question_count"] == 0
    assert registry["ready_authoritative_table_count"] == 0
    assert registry["observed_policy_outcome_superiority_claim"] is False
    assert registry["empirical_superiority_claim"] is False
    assert set(registry["active_action_types"]) == {
        "increase_green_infrastructure",
        "traffic_emission_control",
        "add_community_service",
    }

    assert spatial_readiness["ready"] is True
    assert spatial_readiness["claim_level"] == "spatial_causal_question_contract_only"
    assert spatial_readiness["active_causal_question_count"] == 3
    assert spatial_readiness["underidentified_policy_effect_question_count"] == 3
    assert spatial_readiness["policy_outcome_claim"] is False
    assert "build_spatial_causal_question_registry" not in readiness["next_actions"]


def test_livability_decision_payload_binds_spatial_causal_contracts_to_full_admin_actions():
    payload = routes.load_uwm_livability_decision_payload()

    full_admin = payload["full_admin_decision_package"]
    binding = full_admin["spatial_causal_contract_binding"]

    assert binding["binding_ready"] is True
    assert binding["attached_action_count"] == 6
    assert binding["missing_contract_action_count"] == 0
    assert binding["underidentified_policy_effect_action_count"] == 6
    assert binding["policy_outcome_claim_allowed_action_count"] == 0

    outputs = full_admin["final_outputs"]
    for sequence_key in [
        "planner_recommended_sequence",
        "graph_dqn_recommended_sequence",
        "learned_rollout_recommended_sequence",
    ]:
        for action in outputs[sequence_key]["action_sequence"]:
            assert action["causal_question_id"] == "uwm-cq-green-heat-livability"
            assert action["causal_query"] == (
                "P(heat_risk, livability | do(increase_green_infrastructure), spatial_context)"
            )
            assert action["primary_outcome"] == "heat_risk"
            assert action["identification_status"] == (
                "underidentified_for_observed_policy_effect"
            )
            assert action["required_authoritative_tables"] == [
                "policy_project_history",
                "action_constraint_cost_model",
                "observed_outcome_validation_panel",
                "causal_effect_calibration_panel",
                "human_governance_review_log",
            ]
            assert action["policy_outcome_claim_allowed"] is False
            assert action["observed_policy_outcome_superiority_claim"] is False


def test_livability_decision_payload_exposes_full_action_space_causal_binding():
    payload = routes.load_uwm_livability_decision_payload()

    inventory = payload["full_admin_action_inventory_evidence"]

    assert inventory["full_admin_action_inventory_ready"] is True
    assert inventory["available_action_count"] == 1137
    assert inventory["action_type_counts"] == {
        "increase_green_infrastructure": 81,
        "traffic_emission_control": 77,
        "add_community_service": 979,
    }
    assert inventory["spatial_causal_contract_binding_ready"] is True
    assert inventory["spatial_causal_feasible_action_count"] == 1137
    assert inventory["spatial_causal_attached_action_count"] == 1137
    assert inventory["spatial_causal_missing_contract_action_count"] == 0
    assert inventory["spatial_causal_underidentified_policy_effect_action_count"] == 1137
    assert inventory["spatial_causal_policy_outcome_claim_action_count"] == 0
    assert inventory["observed_policy_outcome_superiority_claim"] is False
    assert inventory["empirical_superiority_claim"] is False
