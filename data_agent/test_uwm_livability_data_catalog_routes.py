from data_agent.api import uwm_livability_data_catalog_routes as routes


def _route_methods(route_list, path):
    for route in route_list:
        if route.path == path:
            return set(route.methods or [])
    return set()


def test_livability_data_catalog_route_is_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes

    route_list = routes.get_uwm_livability_data_catalog_routes()
    frontend_route_list = get_frontend_api_routes()

    assert "GET" in _route_methods(route_list, "/api/uwm/livability-data-catalog")
    assert "POST" in _route_methods(
        route_list,
        "/api/uwm/livability-data-catalog/sync",
    )
    assert "GET" in _route_methods(
        frontend_route_list,
        "/api/uwm/livability-data-catalog",
    )
    assert "POST" in _route_methods(
        frontend_route_list,
        "/api/uwm/livability-data-catalog/sync",
    )


def test_livability_data_catalog_payload_exposes_mmfe_and_rl_training_boundaries():
    payload = routes.load_uwm_livability_data_catalog_payload()

    assert payload["schema"] == routes.UWM_LIVABILITY_DATA_CATALOG_API_SCHEMA
    catalog = payload["data_catalog"]
    assert catalog["catalog_ready"] is True
    assert catalog["mmfe_readiness"]["complete_mmfe_managed_pipeline"] is False
    assert catalog["mmfe_readiness"]["mmfe_state_input_asset_count"] >= 2
    assert catalog["model_based_rl_boundary"]["model_based_rl_training_completed"] is True
    assert catalog["model_based_rl_boundary"]["trained_model_based_q_agent_completed"] is True
    assert catalog["model_based_rl_boundary"]["graph_drl_training_completed"] is True
    assert catalog["model_based_rl_boundary"]["policy_or_value_network_trained"] is False
    assert catalog["model_based_rl_boundary"]["graph_policy_or_value_network_trained"] is True
    assert catalog["model_based_rl_boundary"]["current_planning_mode"] == (
        "trained_graph_dqn_value_network_over_real_data_graph_mdp"
    )
    assert catalog["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert payload["observed_policy_outcome_superiority_claim"] is False

    integration = catalog["data_agent_catalog_integration"]
    assert integration["source_of_truth_table"] == "agent_data_assets"
    assert integration["shadow_catalog"] is False
    assert integration["registration_plan"]["asset_count"] == len(catalog["assets"])
