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
