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
        "local_planning_zip_inventory",
        "livability_endpoint_suite",
        "building_floor_morphology",
        "data_calibrated_mechanism_table",
        "data_calibrated_spatial_spillover_kernel",
        "geographic_similarity_kernel",
        "data_calibrated_planner_replay",
        "full_admin_service_accessibility_surface",
        "full_admin_service_surface_quality_audit",
        "full_admin_livability_target_panel",
        "full_admin_action_inventory",
        "production_state_action_space_assessment",
        "production_action_catalog",
        "production_governance_data_contract",
        "production_governance_data_adapter_readiness",
        "production_governance_input_templates",
        "production_governance_linkage_audit",
        "production_governance_planner_binding_gate",
        "full_admin_data_calibrated_mechanism_table",
        "full_admin_graph_planner_replay",
        "full_admin_graph_drl_training_report",
        "full_admin_learned_world_model_rollout",
        "livability_rl_training_report",
        "livability_graph_drl_training_report",
        "energy_regularized_planner_report",
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

    service_surface = assets_by_id["full_admin_service_accessibility_surface"]
    assert service_surface["schema"] == "uwm.full_admin_service_accessibility_surface.v1"
    assert service_surface["admin_unit_count"] == 1017
    assert service_surface["source_poi_point_count"] == 1194351
    assert service_surface["source_road_count"] == 50366
    assert service_surface["service_missing_admin_count"] == 0
    assert service_surface["admin_units_with_accessibility_score"] == 1017
    assert service_surface["total_service_point_count"] > 1000000
    assert service_surface["total_essential_service_count"] > 10000

    service_quality = assets_by_id["full_admin_service_surface_quality_audit"]
    assert service_quality["schema"] == "uwm.full_admin_service_surface_quality_audit.v1"
    assert service_quality["admin_unit_count"] == 1017
    assert service_quality["endpoint_count"] == 2
    assert service_quality["ready_endpoint_count"] == 2
    assert service_quality["supported_claim"] == (
        "full_admin_service_surface_proxy_quality_beats_static_and_negative_controls"
    )

    geographic_similarity = assets_by_id["geographic_similarity_kernel"]
    assert geographic_similarity["schema"] == "uwm.geographic_similarity_kernel.v1"
    assert geographic_similarity["geographic_similarity_kernel_ready"] is True
    assert geographic_similarity["panel_unit_count"] == 1017
    assert geographic_similarity["similarity_edge_count"] == 5085
    assert geographic_similarity["non_adjacent_similarity_edge_count"] == 4835
    assert geographic_similarity["rotated_target_similarity_control_passed"] is True
    assert geographic_similarity["supported_claim"] == (
        "geographic_similarity_configuration_kernel_ready"
    )

    action_inventory = assets_by_id["full_admin_action_inventory"]
    assert action_inventory["schema"] == "uwm.full_admin_action_inventory.v1"
    assert action_inventory["full_data_guard_passed"] is True
    assert action_inventory["graph_node_count"] == 1017
    assert action_inventory["graph_edge_count"] == 7932
    assert action_inventory["available_action_count"] == 1137
    assert action_inventory["action_type_counts"] == {
        "increase_green_infrastructure": 81,
        "traffic_emission_control": 77,
        "add_community_service": 979,
    }
    assert action_inventory["observed_policy_outcome_superiority_claim"] is False

    production_assessment = assets_by_id["production_state_action_space_assessment"]
    assert production_assessment["schema"] == (
        "uwm.production_state_action_space_assessment.v1"
    )
    assert production_assessment["experiment_scope"] == "full_admin_graph"
    assert production_assessment["graph_node_count"] == 1017
    assert production_assessment["available_action_count"] == 1137
    assert production_assessment["implemented_action_type_count"] == 3
    assert production_assessment["production_action_type_target_count"] >= 30
    assert production_assessment["state_space_blocking_gap_count"] == 7
    assert production_assessment["action_space_blocking_gap_count"] == 5
    assert production_assessment["production_readiness_claim"] is False
    assert production_assessment["observed_policy_outcome_superiority_claim"] is False

    production_action_catalog = assets_by_id["production_action_catalog"]
    assert production_action_catalog["schema"] == "uwm.production_action_catalog.v1"
    assert production_action_catalog["experiment_scope"] == "full_admin_graph"
    assert production_action_catalog["action_catalog_contract_ready"] is True
    assert production_action_catalog["future_authoritative_data_extension_ready"] is True
    assert production_action_catalog["planner_production_action_ready"] is False
    assert production_action_catalog["production_action_type_count"] == 57
    assert production_action_catalog["currently_bound_action_type_count"] == 3
    assert production_action_catalog["currently_bound_feasible_action_count"] == 1137
    assert production_action_catalog["unbound_production_action_type_count"] == 54
    assert production_action_catalog["current_candidate_binding_count"] == 1137
    assert production_action_catalog["observed_policy_outcome_superiority_claim"] is False

    governance_contract = assets_by_id["production_governance_data_contract"]
    assert governance_contract["schema"] == (
        "uwm.production_governance_data_contract.v1"
    )
    assert governance_contract["experiment_scope"] == "full_admin_graph"
    assert governance_contract["governance_data_contract_ready"] is True
    assert governance_contract["planner_governance_binding_ready"] is False
    assert governance_contract["policy_project_history_ready"] is False
    assert governance_contract["constraint_cost_model_ready"] is False
    assert governance_contract["observed_outcome_panel_ready"] is False
    assert governance_contract["production_action_type_count"] == 57
    assert governance_contract["currently_bound_feasible_action_count"] == 1137
    assert governance_contract["required_governance_table_count"] == 5
    assert governance_contract["ready_governance_table_count"] == 0
    assert governance_contract["planning_sample_source_count"] == 15
    assert governance_contract["observed_policy_outcome_superiority_claim"] is False

    governance_adapter = assets_by_id["production_governance_data_adapter_readiness"]
    assert governance_adapter["schema"] == (
        "uwm.production_governance_data_adapter_readiness.v1"
    )
    assert governance_adapter["experiment_scope"] == "full_admin_graph"
    assert governance_adapter["adapter_contract_ready"] is True
    assert governance_adapter["all_required_tables_ready"] is False
    assert governance_adapter["planner_governance_binding_ready"] is False
    assert governance_adapter["expected_table_count"] == 5
    assert governance_adapter["ready_table_count"] == 0
    assert governance_adapter["missing_source_table_count"] == 5
    assert governance_adapter["accepted_authoritative_row_count"] == 0
    assert governance_adapter["observed_policy_outcome_superiority_claim"] is False

    governance_templates = assets_by_id["production_governance_input_templates"]
    assert governance_templates["schema"] == (
        "uwm.production_governance_input_templates.v1"
    )
    assert governance_templates["experiment_scope"] == "full_admin_graph"
    assert governance_templates["template_pack_ready"] is True
    assert governance_templates["authoritative_input_claim"] is False
    assert governance_templates["template_count"] == 5
    assert governance_templates["required_field_count"] == 54
    assert governance_templates["adapter_ready_table_count"] == 0
    assert governance_templates["adapter_missing_source_table_count"] == 5
    assert governance_templates["template_dir_is_adapter_input_dir"] is False
    assert governance_templates["observed_policy_outcome_superiority_claim"] is False

    governance_linkage = assets_by_id["production_governance_linkage_audit"]
    assert governance_linkage["schema"] == (
        "uwm.production_governance_linkage_audit.v1"
    )
    assert governance_linkage["experiment_scope"] == "full_admin_graph"
    assert governance_linkage["linkage_audit_ready"] is True
    assert governance_linkage["all_required_tables_present"] is False
    assert governance_linkage["governance_linkage_ready"] is False
    assert governance_linkage["planner_governance_binding_ready"] is False
    assert governance_linkage["expected_table_count"] == 5
    assert governance_linkage["present_table_count"] == 0
    assert governance_linkage["missing_table_count"] == 5
    assert governance_linkage["linked_project_count"] == 0
    assert governance_linkage["unlinked_project_count"] == 0
    assert governance_linkage["observed_policy_outcome_superiority_claim"] is False

    governance_binding_gate = assets_by_id[
        "production_governance_planner_binding_gate"
    ]
    assert governance_binding_gate["schema"] == (
        "uwm.production_governance_planner_binding_gate.v1"
    )
    assert governance_binding_gate["experiment_scope"] == "full_admin_graph"
    assert governance_binding_gate["binding_gate_ready"] is True
    assert governance_binding_gate["authoritative_governance_data_closure_ready"] is False
    assert governance_binding_gate["planner_governance_binding_ready"] is False
    assert governance_binding_gate["required_gate_count"] == 9
    assert governance_binding_gate["passed_gate_count"] == 2
    assert governance_binding_gate["blocking_gate_count"] == 7
    assert governance_binding_gate["missing_table_count"] == 5
    assert governance_binding_gate["accepted_authoritative_row_count"] == 0
    assert governance_binding_gate["linked_project_count"] == 0
    assert governance_binding_gate["observed_policy_outcome_superiority_claim"] is False

    assert catalog["mmfe_readiness"]["complete_mmfe_managed_pipeline"] is False
    assert catalog["mmfe_readiness"]["local_file_backed_asset_count"] >= 8
    assert catalog["mmfe_readiness"]["mmfe_state_input_asset_count"] >= 2
    assert "register_uwm_assets_in_data_catalog" in catalog["mmfe_readiness"]["required_next_steps"]
    assert "materialize_curated_admin_unit_state_table" in catalog["mmfe_readiness"]["required_next_steps"]

    assert catalog["model_based_rl_boundary"] == {
        "model_based_rl_training_completed": True,
        "trained_model_based_q_agent_completed": True,
        "graph_drl_training_completed": True,
        "energy_regularized_planner_completed": True,
        "policy_or_value_network_trained": False,
        "graph_policy_or_value_network_trained": True,
        "conservative_search_guard_ready": True,
        "full_admin_graph_drl_training_completed": True,
        "current_planning_mode": "energy_regularized_conservative_action_sequence_planner_over_real_data_graph_mdp",
        "allowed_claim": "simulator_grounded_energy_regularized_planner_advantage_not_observed_policy_outcome",
    }
    assert catalog["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert catalog["observed_policy_outcome_superiority_claim"] is False
    assert (
        catalog["full_data_readiness"]["full_admin_graph_planner_replay_completed"]
        is True
    )
    assert (
        catalog["full_data_readiness"]["full_admin_action_inventory_completed"]
        is True
    )
    assert (
        catalog["full_data_readiness"]["full_admin_action_inventory_action_count"]
        == 1137
    )
    assert (
        catalog["full_data_readiness"][
            "full_admin_service_accessibility_surface_completed"
        ]
        is True
    )
    assert (
        catalog["full_data_readiness"][
            "full_admin_service_surface_missing_admin_count"
        ]
        == 0
    )
    assert (
        catalog["full_data_readiness"][
            "full_admin_service_surface_quality_audit_completed"
        ]
        is True
    )
    assert catalog["full_data_readiness"]["full_admin_graph_node_count"] == 1017
    assert catalog["full_data_readiness"]["full_admin_graph_edge_count"] == 7932
    assert catalog["full_data_readiness"]["full_admin_available_action_count"] == 1137
    assert (
        catalog["full_data_readiness"][
            "full_admin_graph_drl_training_completed"
        ]
        is True
    )
    assert (
        catalog["full_data_readiness"]["full_admin_graph_drl_training_sample_count"]
        == 1248
    )
    assert (
        catalog["full_data_readiness"][
            "full_admin_graph_drl_advantage_over_traditional_static"
        ]
        > 0
    )
    assert (
        catalog["full_data_readiness"][
            "full_admin_learned_world_model_rollout_completed"
        ]
        is True
    )
    assert (
        catalog["full_data_readiness"][
            "full_admin_learned_world_model_rollout_transition_count"
        ]
        == 6817
    )
    assert (
        catalog["full_data_readiness"][
            "full_admin_learned_world_model_rollout_advantage_over_static"
        ]
        > 0
    )


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
        "admin_units_geojson",
        "full_admin_service_accessibility_surface",
        "full_admin_service_surface_admin_geometry_input",
    ) in edges
    assert (
        "local_planning_zip_inventory",
        "full_admin_service_accessibility_surface",
        "full_admin_service_surface_local_poi_road_source_inventory",
    ) in edges
    assert (
        "full_admin_service_accessibility_surface",
        "full_admin_service_surface_quality_audit",
        "full_admin_service_surface_quality_input",
    ) in edges
    assert (
        "full_admin_service_surface_quality_audit",
        "full_admin_livability_target_panel",
        "full_admin_service_quality_evidence_input",
    ) in edges
    assert (
        "full_admin_service_accessibility_surface",
        "full_admin_livability_target_panel",
        "full_admin_service_state_input",
    ) in edges
    assert (
        "full_admin_livability_target_panel",
        "full_admin_graph_planner_replay",
        "full_admin_graph_state_input",
    ) in edges
    assert (
        "full_admin_livability_target_panel",
        "full_admin_action_inventory",
        "full_admin_action_inventory_state_input",
    ) in edges
    assert (
        "geographic_similarity_kernel",
        "full_admin_action_inventory",
        "full_admin_action_inventory_similarity_edge_input",
    ) in edges
    assert (
        "full_admin_action_inventory",
        "full_admin_energy_regularized_planner_report",
        "full_admin_energy_planner_feasible_action_inventory_input",
    ) in edges
    assert (
        "full_admin_action_inventory",
        "production_state_action_space_assessment",
        "production_assessment_current_action_space_input",
    ) in edges
    assert (
        "full_admin_livability_decision_package",
        "production_state_action_space_assessment",
        "production_assessment_current_full_admin_scope_input",
    ) in edges
    assert (
        "local_planning_zip_inventory",
        "production_state_action_space_assessment",
        "production_assessment_local_asset_scope_input",
    ) in edges
    assert (
        "production_state_action_space_assessment",
        "production_action_catalog",
        "production_action_catalog_target_ontology_input",
    ) in edges
    assert (
        "full_admin_action_inventory",
        "production_action_catalog",
        "production_action_catalog_current_feasible_binding_input",
    ) in edges
    assert (
        "production_action_catalog",
        "production_governance_data_contract",
        "governance_contract_action_catalog_input",
    ) in edges
    assert (
        "local_planning_zip_inventory",
        "production_governance_data_contract",
        "governance_contract_local_planning_sample_scope_input",
    ) in edges
    assert (
        "production_governance_data_contract",
        "production_governance_data_adapter_readiness",
        "governance_adapter_contract_input",
    ) in edges
    assert (
        "production_governance_data_contract",
        "production_governance_input_templates",
        "governance_input_templates_contract_input",
    ) in edges
    assert (
        "production_governance_data_adapter_readiness",
        "production_governance_input_templates",
        "governance_input_templates_readiness_boundary_input",
    ) in edges
    assert (
        "production_governance_data_adapter_readiness",
        "production_governance_linkage_audit",
        "governance_linkage_adapter_readiness_input",
    ) in edges
    assert (
        "production_governance_input_templates",
        "production_governance_linkage_audit",
        "governance_linkage_expected_table_contract_input",
    ) in edges
    assert (
        "production_action_catalog",
        "production_governance_planner_binding_gate",
        "planner_binding_gate_action_contract_input",
    ) in edges
    assert (
        "production_governance_data_contract",
        "production_governance_planner_binding_gate",
        "planner_binding_gate_governance_contract_input",
    ) in edges
    assert (
        "production_governance_data_adapter_readiness",
        "production_governance_planner_binding_gate",
        "planner_binding_gate_adapter_readiness_input",
    ) in edges
    assert (
        "production_governance_linkage_audit",
        "production_governance_planner_binding_gate",
        "planner_binding_gate_linkage_audit_input",
    ) in edges
    assert (
        "geographic_similarity_kernel",
        "full_admin_graph_planner_replay",
        "full_admin_graph_similarity_edge_input",
    ) in edges
    assert (
        "full_admin_data_calibrated_mechanism_table",
        "full_admin_graph_planner_replay",
        "full_admin_simulator_mechanism_input",
    ) in edges
    assert (
        "full_admin_livability_target_panel",
        "full_admin_graph_drl_training_report",
        "full_admin_graph_drl_state_input",
    ) in edges
    assert (
        "full_admin_data_calibrated_mechanism_table",
        "full_admin_graph_drl_training_report",
        "full_admin_graph_drl_mechanism_input",
    ) in edges
    assert (
        "admin_units_geojson",
        "full_admin_graph_drl_training_report",
        "full_admin_graph_drl_boundary_graph_input",
    ) in edges
    assert (
        "geographic_similarity_kernel",
        "full_admin_graph_drl_training_report",
        "full_admin_graph_drl_similarity_edge_input",
    ) in edges
    assert (
        "full_admin_graph_planner_replay",
        "full_admin_learned_world_model_rollout",
        "full_admin_compact_replay_training_input",
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
        "livability_graph_drl_training_report",
        "energy_regularized_planner_report",
        "search_value_alignment_evidence_input",
    ) in edges
    assert (
        "data_calibrated_spatial_spillover_kernel",
        "energy_regularized_planner_report",
        "energy_regularized_planner_spatial_spillover_input",
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
