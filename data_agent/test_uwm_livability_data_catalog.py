from pathlib import Path

from data_agent.uwm.livability_data_catalog import (
    UWM_LIVABILITY_DATA_CATALOG_SCHEMA,
    build_uwm_livability_data_catalog,
    sync_uwm_livability_assets_to_data_agent_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def test_livability_data_catalog_tracks_real_assets_mmfe_gaps_and_rl_boundary():
    catalog = build_uwm_livability_data_catalog(
        data_root=DATA_ROOT,
        catalog_id="uwm-livability-data-catalog-test",
        created_at="2026-07-07T00:00:00Z",
    )

    assert catalog["schema"] == UWM_LIVABILITY_DATA_CATALOG_SCHEMA
    assert catalog["catalog_ready"] is True
    assert catalog["data_root"].endswith("data/uwm_public_proxy/chongqing_central")

    assets_by_id = {asset["asset_id"]: asset for asset in catalog["assets"]}
    for required_asset in [
        "multisource_livability_scene",
        "admin_units_geojson",
        "livability_endpoint_suite",
        "building_floor_morphology",
        "data_calibrated_mechanism_table",
        "data_calibrated_spatial_spillover_kernel",
        "data_calibrated_planner_replay",
        "livability_rl_training_report",
        "livability_graph_drl_training_report",
        "livability_decision_package",
        "traditional_vs_world_model_demo",
    ]:
        assert assets_by_id[required_asset]["exists"] is True
        assert assets_by_id[required_asset]["size_bytes"] > 0

    scene = assets_by_id["multisource_livability_scene"]
    assert scene["schema"] == "uwm.multisource_livability_scene.v1"
    assert scene["admin_unit_count"] == 36
    assert "admin_livability_target_complete_bbox" in scene["data_sources_used"]
    assert "unicom_latent_mobility_graph" in scene["data_sources_used"]

    assert catalog["mmfe_readiness"]["complete_mmfe_managed_pipeline"] is False
    assert catalog["mmfe_readiness"]["local_file_backed_asset_count"] >= 8
    assert catalog["mmfe_readiness"]["mmfe_state_input_asset_count"] >= 2
    assert "register_uwm_assets_in_data_catalog" in catalog["mmfe_readiness"]["required_next_steps"]
    assert "materialize_curated_admin_unit_state_table" in catalog["mmfe_readiness"]["required_next_steps"]

    assert catalog["model_based_rl_boundary"] == {
        "model_based_rl_training_completed": True,
        "trained_model_based_q_agent_completed": True,
        "graph_drl_training_completed": True,
        "policy_or_value_network_trained": False,
        "graph_policy_or_value_network_trained": True,
        "current_planning_mode": "trained_graph_dqn_value_network_over_real_data_graph_mdp",
        "allowed_claim": "simulator_grounded_graph_drl_training_advantage_not_observed_policy_outcome",
    }
    assert catalog["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert catalog["observed_policy_outcome_superiority_claim"] is False


def test_livability_data_catalog_records_lineage_from_raw_assets_to_decision_package():
    catalog = build_uwm_livability_data_catalog(
        data_root=DATA_ROOT,
        catalog_id="uwm-livability-data-catalog-test",
        created_at="2026-07-07T00:00:00Z",
    )

    edges = {
        (edge["from"], edge["to"], edge["relation"])
        for edge in catalog["lineage_edges"]
    }

    assert (
        "multisource_livability_scene",
        "livability_endpoint_suite",
        "endpoint_validation_input",
    ) in edges
    assert (
        "data_calibrated_mechanism_table",
        "data_calibrated_planner_replay",
        "simulator_mechanism_input",
    ) in edges
    assert (
        "data_calibrated_spatial_spillover_kernel",
        "livability_decision_package",
        "spatial_spillover_kernel_decision_evidence_input",
    ) in edges
    assert (
        "data_calibrated_planner_replay",
        "livability_decision_package",
        "planner_replay_input",
    ) in edges
    assert (
        "data_calibrated_spatial_spillover_kernel",
        "livability_rl_training_report",
        "rl_training_spatial_spillover_input",
    ) in edges
    assert (
        "livability_rl_training_report",
        "livability_decision_package",
        "trained_model_based_rl_evidence_input",
    ) in edges
    assert (
        "data_calibrated_spatial_spillover_kernel",
        "livability_graph_drl_training_report",
        "graph_drl_spatial_spillover_input",
    ) in edges
    assert (
        "livability_graph_drl_training_report",
        "livability_decision_package",
        "trained_graph_drl_evidence_input",
    ) in edges
    assert (
        "livability_decision_package",
        "traditional_vs_world_model_demo",
        "uwm_output_input",
    ) in edges


def test_livability_data_catalog_projects_to_existing_data_agent_catalog_contract():
    catalog = build_uwm_livability_data_catalog(
        data_root=DATA_ROOT,
        catalog_id="uwm-livability-data-catalog-test",
        created_at="2026-07-07T00:00:00Z",
    )

    integration = catalog["data_agent_catalog_integration"]

    assert integration["source_of_truth_table"] == "agent_data_assets"
    assert integration["lineage_table"] == "agent_asset_lineage"
    assert integration["shadow_catalog"] is False
    assert integration["integration_mode"] == "scene_projection_over_existing_data_catalog"
    assert integration["registration_plan"]["asset_count"] == len(catalog["assets"])
    assert integration["registration_plan"]["lineage_edge_count"] == len(catalog["lineage_edges"])
    assert "/api/catalog" in integration["reuse_existing_api_routes"]
    assert "/api/metadata/search" in integration["reuse_existing_api_routes"]
    assert "/api/catalog/{id}/cross-system-lineage" in integration["reuse_existing_api_routes"]

    first_spec = integration["registration_plan"]["assets"][0]
    assert first_spec["target_table"] == "agent_data_assets"
    assert first_spec["asset_name"].startswith("uwm_livability__")
    assert first_spec["technical"]["storage"]["backend"] == "local"
    assert first_spec["business"]["classification"]["domain"] == "urban_livability"
    assert "uwm_livability" in first_spec["business"]["semantic"]["keywords"]
    assert first_spec["operational"]["creation"]["tool"] == "uwm_livability_pipeline"


def test_sync_uwm_livability_assets_uses_existing_catalog_and_lineage_adapters():
    catalog = build_uwm_livability_data_catalog(
        data_root=DATA_ROOT,
        catalog_id="uwm-livability-data-catalog-test",
        created_at="2026-07-07T00:00:00Z",
    )
    integration = catalog["data_agent_catalog_integration"]
    asset_specs = integration["registration_plan"]["assets"][:3]
    edge_specs = [
        edge
        for edge in integration["registration_plan"]["lineage_edges"]
        if edge["source_asset_key"] in {spec["uwm_asset_id"] for spec in asset_specs}
        and edge["target_asset_key"] in {spec["uwm_asset_id"] for spec in asset_specs}
    ]
    plan = {"assets": asset_specs, "lineage_edges": edge_specs}

    registered_paths = []
    updated_metadata = []
    lineage_edges = []

    def fake_register(path, **kwargs):
        registered_paths.append((path, kwargs))
        return len(registered_paths) + 100

    class FakeMetadataManager:
        def update_metadata(self, asset_id, **kwargs):
            updated_metadata.append((asset_id, kwargs))
            return True

    def fake_add_lineage_edge(**kwargs):
        lineage_edges.append(kwargs)
        return len(lineage_edges) + 500

    result = sync_uwm_livability_assets_to_data_agent_catalog(
        plan,
        register_path=fake_register,
        metadata_manager=FakeMetadataManager(),
        add_lineage=fake_add_lineage_edge,
    )

    assert result["target_tables"] == ["agent_data_assets", "agent_asset_lineage"]
    assert result["registered_asset_count"] == len(asset_specs)
    assert result["metadata_updated_count"] == len(asset_specs)
    assert result["lineage_edge_count"] == len(edge_specs)
    assert all(kwargs["creation_tool"] == "uwm_livability_pipeline" for _, kwargs in registered_paths)
    assert all(kwargs["technical"]["uwm"]["stage"] for _, kwargs in updated_metadata)
    assert all(edge["tool_name"] == "uwm_livability_pipeline" for edge in lineage_edges)
