"""Data catalog and lineage readiness for UWM livability assets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


UWM_LIVABILITY_DATA_CATALOG_SCHEMA = "uwm.livability_data_catalog.v1"


CORE_ASSET_SPECS = [
    {
        "asset_id": "multisource_livability_scene",
        "role": "renderer_state_scene",
        "path": "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json",
        "stage": "renderer",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "admin_units_geojson",
        "role": "admin_unit_geometry",
        "path": "admin_units/chongqing_township_admin_units.geojson",
        "stage": "renderer",
        "format": "geojson",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "local_planning_zip_inventory",
        "role": "local_planning_source_inventory",
        "path": "local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        "stage": "data_foundation",
        "format": "csv",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "building_floor_morphology",
        "role": "endpoint_25d_morphology",
        "path": "building_floor_morphology_2026_07_07/uwm_building_floor_morphology.json",
        "stage": "endpoint_validation",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "livability_endpoint_suite",
        "role": "final_endpoint_validation",
        "path": "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json",
        "stage": "endpoint_validation",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "data_calibrated_mechanism_table",
        "role": "simulator_mechanism_table",
        "path": "data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json",
        "stage": "simulator",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "data_calibrated_spatial_spillover_kernel",
        "role": "simulator_spatial_spillover_kernel",
        "path": "data_calibrated_spatial_spillover_kernel_2026_07_07/uwm_data_calibrated_spatial_spillover_kernel.json",
        "stage": "simulator",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "geographic_similarity_kernel",
        "role": "graph_geographic_configuration_similarity_kernel",
        "path": "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json",
        "stage": "renderer_graph_prior",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "data_calibrated_planner_replay",
        "role": "planner_graph_search_replay",
        "path": "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json",
        "stage": "planner",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "full_admin_service_accessibility_surface",
        "role": "full_admin_local_poi_road_service_accessibility_surface",
        "path": "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json",
        "stage": "renderer_state_input",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "full_admin_service_surface_quality_audit",
        "role": "full_admin_service_surface_proxy_quality_audit",
        "path": "full_admin_service_surface_quality_audit_2026_07_08/uwm_full_admin_service_surface_quality_audit.json",
        "stage": "endpoint_validation",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "full_admin_livability_target_panel",
        "role": "full_admin_graph_livability_target_panel",
        "path": "admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json",
        "stage": "renderer_state_input",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "full_admin_action_inventory",
        "role": "full_admin_graph_feasible_action_inventory",
        "path": "full_admin_action_inventory_2026_07_08/uwm_full_admin_action_inventory.json",
        "stage": "planner_action_space",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "production_state_action_space_assessment",
        "role": "production_state_action_space_gap_assessment",
        "path": "production_state_action_space_assessment_2026_07_08/uwm_production_state_action_space_assessment.json",
        "stage": "production_readiness_gap_analysis",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "production_action_catalog",
        "role": "production_parameterized_action_contract_catalog",
        "path": "production_action_catalog_2026_07_08/uwm_production_action_catalog.json",
        "stage": "production_action_space_contract",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "production_governance_data_contract",
        "role": "production_policy_constraint_outcome_governance_data_contract",
        "path": "production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json",
        "stage": "production_governance_data_contract",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "production_governance_data_adapter_readiness",
        "role": "production_authoritative_governance_table_adapter_readiness",
        "path": "production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json",
        "stage": "production_governance_data_adapter_readiness",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "production_governance_input_templates",
        "role": "production_authoritative_governance_input_templates",
        "path": "production_governance_input_templates_2026_07_08/uwm_production_governance_input_templates.json",
        "stage": "production_governance_input_templates",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "production_governance_linkage_audit",
        "role": "production_authoritative_governance_cross_table_linkage_audit",
        "path": "production_governance_linkage_audit_2026_07_08/uwm_production_governance_linkage_audit.json",
        "stage": "production_governance_linkage_audit",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "production_governance_planner_binding_gate",
        "role": "production_authoritative_governance_planner_binding_gate",
        "path": "production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json",
        "stage": "production_governance_planner_binding_gate",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "full_admin_data_calibrated_mechanism_table",
        "role": "full_admin_graph_simulator_mechanism_table",
        "path": "data_calibrated_mechanism_table_full_admin_graph_2026_07_08/uwm_full_admin_graph_data_calibrated_mechanism_table.json",
        "stage": "simulator",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "full_admin_graph_planner_replay",
        "role": "full_admin_graph_planner_replay",
        "path": "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json",
        "stage": "planner",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "full_admin_graph_drl_training_report",
        "role": "full_admin_graph_trained_graph_dqn_value_network_evidence",
        "path": "livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json",
        "stage": "planner_graph_drl_training",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "full_admin_learned_world_model_rollout",
        "role": "full_admin_graph_learned_dynamics_rollout_planner_evidence",
        "path": "learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json",
        "stage": "planner_learned_dynamics",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "full_admin_livability_decision_package",
        "role": "full_admin_final_counterfactual_decision_package",
        "path": "full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json",
        "stage": "decision_package",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "full_admin_energy_regularized_planner_report",
        "role": "full_admin_conservative_energy_regularized_planner_evidence",
        "path": "energy_regularized_planner_full_admin_graph_2026_07_08/uwm_full_admin_graph_energy_regularized_planner_report.json",
        "stage": "planner_conservative_search",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "livability_rl_training_report",
        "role": "trained_model_based_q_agent_evidence",
        "path": "livability_rl_training_2026_07_07/uwm_livability_rl_training_report.json",
        "stage": "planner_rl_training",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "livability_graph_drl_training_report",
        "role": "trained_graph_dqn_value_network_evidence",
        "path": "livability_graph_drl_training_2026_07_07/uwm_livability_graph_drl_training_report.json",
        "stage": "planner_graph_drl_training",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "energy_regularized_planner_report",
        "role": "conservative_energy_regularized_planner_evidence",
        "path": "energy_regularized_planner_2026_07_07/uwm_energy_regularized_planner_report.json",
        "stage": "planner_conservative_search",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "endpoint_aligned_planner_evaluator",
        "role": "endpoint_aligned_planner_evidence",
        "path": "endpoint_aligned_planner_evaluator_2026_07_07/uwm_endpoint_aligned_planner_evaluator.json",
        "stage": "planner_evaluation",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "spatial_spillover_planner_evaluator",
        "role": "spatial_spillover_planner_evidence",
        "path": "spatial_spillover_planner_evaluator_2026_07_07/uwm_spatial_spillover_planner_evaluator.json",
        "stage": "planner_evaluation",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "livability_decision_package",
        "role": "final_counterfactual_decision_package",
        "path": "livability_decision_package_2026_07_07/uwm_livability_decision_package.json",
        "stage": "decision_package",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
    {
        "asset_id": "traditional_vs_world_model_demo",
        "role": "same_data_customer_demo_comparison",
        "path": "traditional_vs_world_model_demo_2026_07_07/uwm_traditional_vs_world_model_demo.json",
        "stage": "demo_output",
        "format": "json",
        "mmfe_status": "prepared_local_asset_not_registered_as_managed_mmfe_product",
    },
]


def build_uwm_livability_data_catalog(
    *,
    data_root: str | Path,
    catalog_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Build a machine-readable catalog from the current local UWM assets."""

    root = Path(data_root).expanduser()
    core_assets = [_asset_from_spec(root, spec) for spec in CORE_ASSET_SPECS]
    mmfe_state_assets = _mmfe_state_input_assets(root)
    assets = core_assets + mmfe_state_assets
    lineage_edges = _lineage_edges()
    assets_by_id = {str(asset.get("asset_id")): asset for asset in assets}
    rl_asset = assets_by_id.get("livability_rl_training_report") or {}
    graph_drl_asset = assets_by_id.get("livability_graph_drl_training_report") or {}
    energy_planner_asset = assets_by_id.get("energy_regularized_planner_report") or {}
    full_admin_service_surface_asset = (
        assets_by_id.get("full_admin_service_accessibility_surface") or {}
    )
    full_admin_service_quality_asset = (
        assets_by_id.get("full_admin_service_surface_quality_audit") or {}
    )
    geographic_similarity_asset = assets_by_id.get("geographic_similarity_kernel") or {}
    full_admin_planner_asset = assets_by_id.get("full_admin_graph_planner_replay") or {}
    full_admin_graph_drl_asset = (
        assets_by_id.get("full_admin_graph_drl_training_report") or {}
    )
    full_admin_learned_rollout_asset = (
        assets_by_id.get("full_admin_learned_world_model_rollout") or {}
    )
    full_admin_decision_package_asset = (
        assets_by_id.get("full_admin_livability_decision_package") or {}
    )
    full_admin_action_inventory_asset = (
        assets_by_id.get("full_admin_action_inventory") or {}
    )
    full_admin_energy_planner_asset = (
        assets_by_id.get("full_admin_energy_regularized_planner_report") or {}
    )
    rl_training_completed = (
        rl_asset.get("exists") is True
        and rl_asset.get("schema") == "uwm.livability_rl_training_report.v1"
        and rl_asset.get("supported_claim")
        == "trained_model_based_q_agent_improves_same_scene_static_livability_baseline"
    )
    graph_drl_training_completed = (
        graph_drl_asset.get("exists") is True
        and graph_drl_asset.get("schema")
        == "uwm.livability_graph_drl_training_report.v1"
        and graph_drl_asset.get("supported_claim")
        == "graph_dqn_value_network_improves_same_scene_static_livability_baseline"
        and graph_drl_asset.get("policy_or_value_network_trained") is True
    )
    energy_regularized_planner_completed = (
        energy_planner_asset.get("exists") is True
        and energy_planner_asset.get("schema")
        == "uwm.energy_regularized_action_sequence_planner.v1"
        and energy_planner_asset.get("supported_claim")
        == "energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static"
        and energy_planner_asset.get("planner_exploitation_guard_passed") is True
        and energy_planner_asset.get("search_value_alignment_ready") is True
    )
    full_data_readiness = _full_data_readiness(
        full_admin_service_surface_asset,
        full_admin_service_quality_asset,
        geographic_similarity_asset,
        full_admin_planner_asset,
        full_admin_graph_drl_asset,
        full_admin_learned_rollout_asset,
        full_admin_decision_package_asset,
        full_admin_action_inventory_asset,
        full_admin_energy_planner_asset,
    )
    core_ready = all(asset["exists"] for asset in core_assets)
    mmfe_count = len(mmfe_state_assets)
    local_count = sum(1 for asset in assets if asset["exists"])
    if energy_regularized_planner_completed:
        current_planning_mode = (
            "energy_regularized_conservative_action_sequence_planner_over_real_data_graph_mdp"
        )
        allowed_claim = (
            "simulator_grounded_energy_regularized_planner_advantage_not_observed_policy_outcome"
        )
    elif graph_drl_training_completed:
        current_planning_mode = (
            "trained_graph_dqn_value_network_over_real_data_graph_mdp"
        )
        allowed_claim = (
            "simulator_grounded_graph_drl_training_advantage_not_observed_policy_outcome"
        )
    elif rl_training_completed:
        current_planning_mode = (
            "trained_tabular_model_based_q_agent_over_real_data_graph_mdp"
        )
        allowed_claim = (
            "simulator_grounded_model_based_rl_training_advantage_not_observed_policy_outcome"
        )
    else:
        current_planning_mode = (
            "data_calibrated_model_based_graph_search_without_rl_policy_training"
        )
        allowed_claim = "model_based_planning_replay_not_trained_rl_agent"
    return {
        "schema": UWM_LIVABILITY_DATA_CATALOG_SCHEMA,
        "catalog_id": catalog_id,
        "created_at": created_at,
        "data_root": str(root),
        "catalog_ready": core_ready,
        "assets": assets,
        "lineage_edges": lineage_edges,
        "data_agent_catalog_integration": _data_agent_catalog_integration(
            assets=assets,
            lineage_edges=lineage_edges,
            catalog_id=catalog_id,
            created_at=created_at,
        ),
        "mmfe_readiness": {
            "complete_mmfe_managed_pipeline": False,
            "reason": (
                "current UWM livability pipeline reads prepared local files; "
                "MMFE state-input artifacts exist but the full assets are not yet "
                "registered as managed catalog/lakehouse products"
            ),
            "local_file_backed_asset_count": local_count,
            "core_asset_count": len(core_assets),
            "core_asset_ready_count": sum(1 for asset in core_assets if asset["exists"]),
            "mmfe_state_input_asset_count": mmfe_count,
            "mmfe_state_input_assets": [
                asset["asset_id"] for asset in mmfe_state_assets
            ],
            "required_next_steps": [
                "register_uwm_assets_in_data_catalog",
                "materialize_curated_admin_unit_state_table",
                "publish_curated_assets_to_mmfe_lakehouse",
                "attach_stac_or_catalog_metadata",
                "version_renderer_simulator_planner_inputs",
            ],
        },
        "model_based_rl_boundary": {
            "model_based_rl_training_completed": rl_training_completed,
            "trained_model_based_q_agent_completed": rl_training_completed,
            "graph_drl_training_completed": graph_drl_training_completed,
            "energy_regularized_planner_completed": energy_regularized_planner_completed,
            "policy_or_value_network_trained": False,
            "graph_policy_or_value_network_trained": graph_drl_training_completed,
            "conservative_search_guard_ready": energy_regularized_planner_completed,
            "full_admin_graph_drl_training_completed": (
                full_data_readiness["full_admin_graph_drl_training_completed"]
            ),
            "current_planning_mode": current_planning_mode,
            "allowed_claim": allowed_claim,
        },
        "full_data_readiness": full_data_readiness,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if core_ready else "not_for_claim",
            "reason": (
                "catalog verifies current local UWM data lineage and readiness; "
                "it does not claim full MMFE-managed ingestion or observed "
                "policy outcome superiority; graph neural value training remains "
                "simulator-grounded"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def sync_uwm_livability_assets_to_data_agent_catalog(
    registration_plan: dict[str, Any],
    *,
    register_path=None,
    metadata_manager=None,
    add_lineage=None,
) -> dict[str, Any]:
    """Register UWM livability assets through the existing GIS Data Agent catalog.

    This function intentionally uses the platform catalog/metadata/lineage
    adapters. It does not create a second source of truth for data management.
    """

    if register_path is None:
        from data_agent.data_catalog import auto_register_from_path as register_path
    if metadata_manager is None:
        from data_agent.metadata_manager import MetadataManager

        metadata_manager = MetadataManager()
    if add_lineage is None:
        from data_agent.data_catalog import add_lineage_edge as add_lineage

    asset_specs = [
        spec
        for spec in registration_plan.get("assets", [])
        if isinstance(spec, dict) and spec.get("exists") is True
    ]
    edge_specs = [
        edge
        for edge in registration_plan.get("lineage_edges", [])
        if isinstance(edge, dict)
    ]

    id_by_uwm_asset: dict[str, int] = {}
    metadata_updated = 0
    lineage_count = 0
    errors: list[dict[str, Any]] = []

    for spec in asset_specs:
        storage = (spec.get("technical") or {}).get("storage") or {}
        operational = spec.get("operational") or {}
        creation = operational.get("creation") or {}
        path = str(storage.get("path") or "")
        uwm_asset_id = str(spec.get("uwm_asset_id") or "")
        if not path or not uwm_asset_id:
            errors.append({"asset": uwm_asset_id, "error": "missing path or uwm_asset_id"})
            continue
        try:
            registered_id = register_path(
                path,
                creation_tool="uwm_livability_pipeline",
                creation_params=creation.get("params") or {},
                storage_backend="local",
                source_assets=[],
                pipeline_run_id=creation.get("pipeline_run_id") or "",
            )
        except Exception as exc:
            errors.append({"asset": uwm_asset_id, "error": str(exc)})
            continue
        if not registered_id:
            errors.append({"asset": uwm_asset_id, "error": "catalog registration returned no id"})
            continue
        id_by_uwm_asset[uwm_asset_id] = int(registered_id)
        if metadata_manager.update_metadata(
            int(registered_id),
            technical=spec.get("technical") or {},
            business=spec.get("business") or {},
            operational=operational,
            lineage=spec.get("lineage") or {},
        ):
            metadata_updated += 1

    for edge in edge_specs:
        source_id = id_by_uwm_asset.get(str(edge.get("source_asset_key") or ""))
        target_id = id_by_uwm_asset.get(str(edge.get("target_asset_key") or ""))
        if not source_id or not target_id:
            continue
        try:
            edge_id = add_lineage(
                source_asset_id=source_id,
                target_asset_id=target_id,
                relationship=edge.get("relationship") or "derives_from",
                tool_name="uwm_livability_pipeline",
                pipeline_run_id=edge.get("pipeline_run_id") or "",
            )
        except Exception as exc:
            errors.append({"edge": edge, "error": str(exc)})
            continue
        if edge_id:
            lineage_count += 1

    return {
        "schema": "uwm.livability_data_agent_catalog_sync.v1",
        "source_of_truth_table": "agent_data_assets",
        "target_tables": ["agent_data_assets", "agent_asset_lineage"],
        "registered_asset_count": len(id_by_uwm_asset),
        "metadata_updated_count": metadata_updated,
        "lineage_edge_count": lineage_count,
        "skipped_lineage_edge_count": max(0, len(edge_specs) - lineage_count),
        "asset_ids_by_uwm_asset": id_by_uwm_asset,
        "errors": errors,
    }


def _asset_from_spec(root: Path, spec: dict[str, str]) -> dict[str, Any]:
    path = root / spec["path"]
    payload = _read_json_if_possible(path) if spec["format"] == "json" else {}
    asset = {
        "asset_id": spec["asset_id"],
        "role": spec["role"],
        "stage": spec["stage"],
        "format": spec["format"],
        "path": str(path),
        "relative_path": spec["path"],
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "mmfe_status": spec["mmfe_status"],
    }
    if payload:
        asset["schema"] = payload.get("schema")
        if "admin_unit_count" in payload:
            asset["admin_unit_count"] = _int(payload.get("admin_unit_count"))
        if "source_feature_counts" in payload:
            asset["source_feature_counts"] = payload.get("source_feature_counts") or {}
            asset["source_poi_point_count"] = _int(
                asset["source_feature_counts"].get("poi_points")
            )
            asset["source_road_count"] = _int(
                asset["source_feature_counts"].get("roads")
            )
        if "coverage" in payload:
            coverage = payload.get("coverage") or {}
            asset["surface_type"] = coverage.get("surface_type")
            asset["service_missing_admin_count"] = _int(
                coverage.get("service_missing_admin_count")
            )
            asset["admin_units_with_service_points"] = _int(
                coverage.get("admin_units_with_service_points")
            )
            asset["admin_units_with_road_context"] = _int(
                coverage.get("admin_units_with_road_context")
            )
            asset["admin_units_with_accessibility_score"] = _int(
                coverage.get("admin_units_with_accessibility_score")
            )
        if "total_service_point_count" in payload:
            asset["total_service_point_count"] = _int(
                payload.get("total_service_point_count")
            )
        if "total_essential_service_count" in payload:
            asset["total_essential_service_count"] = _int(
                payload.get("total_essential_service_count")
            )
        if "endpoint_count" in payload:
            asset["endpoint_count"] = _int(payload.get("endpoint_count"))
        if "ready_endpoint_count" in payload:
            asset["ready_endpoint_count"] = _int(payload.get("ready_endpoint_count"))
        if "full_admin_service_surface_quality_audit_ready" in payload:
            asset["full_admin_service_surface_quality_audit_ready"] = bool(
                payload.get("full_admin_service_surface_quality_audit_ready")
            )
        if payload.get("schema") == "uwm.geographic_similarity_kernel.v1":
            summary = payload.get("summary") or {}
            controls = payload.get("negative_controls") or {}
            features = payload.get("configuration_features") or {}
            asset["geographic_similarity_kernel_ready"] = bool(
                payload.get("geographic_similarity_kernel_ready")
            )
            asset["panel_unit_count"] = _int(summary.get("panel_unit_count"))
            asset["kernel_source_unit_count"] = _int(
                summary.get("kernel_source_unit_count")
            )
            asset["similarity_edge_count"] = _int(
                summary.get("similarity_edge_count")
            )
            asset["adjacent_similarity_edge_count"] = _int(
                summary.get("adjacent_similarity_edge_count")
            )
            asset["non_adjacent_similarity_edge_count"] = _int(
                summary.get("non_adjacent_similarity_edge_count")
            )
            asset["mean_configuration_similarity"] = _float(
                summary.get("mean_configuration_similarity")
            )
            asset["uses_coordinates_as_similarity_features"] = bool(
                features.get("uses_coordinates_as_similarity_features")
            )
            asset["rotated_target_similarity_control_passed"] = bool(
                controls.get("rotated_target_similarity_control_passed")
            )
        if "data_sources_used" in payload:
            asset["data_sources_used"] = list(payload.get("data_sources_used") or [])
        if "source_coverage" in payload:
            asset["source_coverage_keys"] = sorted(
                str(key) for key in (payload.get("source_coverage") or {}).keys()
            )
        if "claim_boundary" in payload:
            asset["claim_level"] = (payload.get("claim_boundary") or {}).get(
                "max_claim_level"
            )
        if "experiment_scope" in payload:
            asset["experiment_scope"] = payload.get("experiment_scope")
        if "joined_admin_count" in payload:
            asset["joined_admin_count"] = _int(payload.get("joined_admin_count"))
        if "source_admin_count" in payload:
            asset["source_admin_count"] = _int(payload.get("source_admin_count"))
        if "service_matched_admin_count" in payload:
            asset["service_matched_admin_count"] = _int(
                payload.get("service_matched_admin_count")
            )
        if "service_missing_admin_count" in payload:
            asset["service_missing_admin_count"] = _int(
                payload.get("service_missing_admin_count")
            )
        if "full_data_guard" in payload:
            guard = payload.get("full_data_guard") or {}
            asset["full_data_guard_passed"] = guard.get("passed") is True
            asset["full_data_rendered_node_count"] = _int(
                guard.get("rendered_node_count")
            )
            asset["full_data_observed_graph_node_count"] = _int(
                guard.get("observed_graph_node_count")
            )
            asset["full_data_required_graph_node_count"] = _int(
                guard.get("required_graph_node_count")
            )
        if payload.get("schema") == "uwm.full_admin_action_inventory.v1":
            guard = payload.get("full_data_guard") or {}
            summary = payload.get("summary") or {}
            asset["graph_node_count"] = _int(guard.get("graph_node_count"))
            asset["graph_edge_count"] = _int(guard.get("graph_edge_count"))
            asset["available_action_count"] = _int(
                guard.get("available_action_count")
            )
            asset["candidate_action_mask_trace_count"] = _int(
                summary.get("candidate_action_mask_trace_count")
            )
            asset["action_type_counts"] = dict(
                summary.get("action_type_counts") or {}
            )
            asset["mask_reason_counts"] = dict(
                summary.get("mask_reason_counts") or {}
            )
        if (
            payload.get("schema")
            == "uwm.production_state_action_space_assessment.v1"
        ):
            scope = payload.get("current_implemented_scope") or {}
            action_space = payload.get("current_action_space") or {}
            gap_summary = payload.get("production_gap_summary") or {}
            asset["graph_node_count"] = _int(scope.get("graph_node_count"))
            asset["graph_edge_count"] = _int(scope.get("graph_edge_count"))
            asset["available_action_count"] = _int(
                scope.get("available_action_count")
            )
            asset["implemented_action_type_count"] = _int(
                action_space.get("implemented_action_type_count")
            )
            asset["production_action_type_target_count"] = _int(
                payload.get("production_action_type_target_count")
            )
            asset["implemented_action_family_count"] = _int(
                payload.get("implemented_action_family_count")
            )
            asset["missing_action_family_count"] = _int(
                payload.get("missing_action_family_count")
            )
            asset["state_space_blocking_gap_count"] = _int(
                gap_summary.get("state_space_blocking_gap_count")
            )
            asset["action_space_blocking_gap_count"] = _int(
                gap_summary.get("action_space_blocking_gap_count")
            )
            asset["production_readiness_claim"] = bool(
                payload.get("production_readiness_claim")
            )
        if payload.get("schema") == "uwm.production_action_catalog.v1":
            summary = payload.get("summary") or {}
            asset["action_catalog_contract_ready"] = bool(
                payload.get("action_catalog_contract_ready")
            )
            asset["future_authoritative_data_extension_ready"] = bool(
                payload.get("future_authoritative_data_extension_ready")
            )
            asset["planner_production_action_ready"] = bool(
                payload.get("planner_production_action_ready")
            )
            asset["policy_project_history_ready"] = bool(
                payload.get("policy_project_history_ready")
            )
            asset["constraint_cost_model_ready"] = bool(
                payload.get("constraint_cost_model_ready")
            )
            asset["observed_policy_outcome_panel_ready"] = bool(
                payload.get("observed_policy_outcome_panel_ready")
            )
            asset["production_action_type_count"] = _int(
                summary.get("production_action_type_count")
            )
            asset["currently_bound_action_type_count"] = _int(
                summary.get("currently_bound_action_type_count")
            )
            asset["currently_bound_feasible_action_count"] = _int(
                summary.get("currently_bound_feasible_action_count")
            )
            asset["unbound_production_action_type_count"] = _int(
                summary.get("unbound_production_action_type_count")
            )
            asset["current_candidate_binding_count"] = len(
                payload.get("current_candidate_bindings") or []
            )
            asset["production_readiness_claim"] = bool(
                payload.get("production_readiness_claim")
            )
        if payload.get("schema") == "uwm.production_governance_data_contract.v1":
            summary = payload.get("summary") or {}
            asset["governance_data_contract_ready"] = bool(
                payload.get("governance_data_contract_ready")
            )
            asset["future_authoritative_data_extension_ready"] = bool(
                payload.get("future_authoritative_data_extension_ready")
            )
            asset["planner_governance_binding_ready"] = bool(
                payload.get("planner_governance_binding_ready")
            )
            asset["policy_project_history_ready"] = bool(
                payload.get("policy_project_history_ready")
            )
            asset["constraint_cost_model_ready"] = bool(
                payload.get("constraint_cost_model_ready")
            )
            asset["observed_outcome_panel_ready"] = bool(
                payload.get("observed_outcome_panel_ready")
            )
            asset["causal_effect_calibration_ready"] = bool(
                payload.get("causal_effect_calibration_ready")
            )
            asset["human_governance_review_ready"] = bool(
                payload.get("human_governance_review_ready")
            )
            asset["production_action_type_count"] = _int(
                summary.get("production_action_type_count")
            )
            asset["currently_bound_feasible_action_count"] = _int(
                summary.get("currently_bound_feasible_action_count")
            )
            asset["required_governance_table_count"] = _int(
                summary.get("required_governance_table_count")
            )
            asset["ready_governance_table_count"] = _int(
                summary.get("ready_governance_table_count")
            )
            asset["planning_sample_source_count"] = _int(
                summary.get("planning_sample_source_count")
            )
            asset["production_readiness_claim"] = bool(
                payload.get("production_readiness_claim")
            )
        if (
            payload.get("schema")
            == "uwm.production_governance_data_adapter_readiness.v1"
        ):
            summary = payload.get("summary") or {}
            asset["adapter_contract_ready"] = bool(
                payload.get("adapter_contract_ready")
            )
            asset["all_required_tables_ready"] = bool(
                payload.get("all_required_tables_ready")
            )
            asset["planner_governance_binding_ready"] = bool(
                payload.get("planner_governance_binding_ready")
            )
            asset["expected_table_count"] = _int(
                summary.get("expected_table_count")
            )
            asset["ready_table_count"] = _int(summary.get("ready_table_count"))
            asset["missing_source_table_count"] = _int(
                summary.get("missing_source_table_count")
            )
            asset["schema_invalid_table_count"] = _int(
                summary.get("schema_invalid_table_count")
            )
            asset["total_row_count"] = _int(summary.get("total_row_count"))
            asset["accepted_authoritative_row_count"] = _int(
                summary.get("accepted_authoritative_row_count")
            )
            asset["rejected_row_count"] = _int(summary.get("rejected_row_count"))
            asset["production_readiness_claim"] = bool(
                payload.get("production_readiness_claim")
            )
        if payload.get("schema") == "uwm.production_governance_input_templates.v1":
            summary = payload.get("summary") or {}
            asset["template_pack_ready"] = bool(payload.get("template_pack_ready"))
            asset["authoritative_input_claim"] = bool(
                payload.get("authoritative_input_claim")
            )
            asset["template_count"] = _int(summary.get("template_count"))
            asset["required_field_count"] = _int(
                summary.get("required_field_count")
            )
            asset["adapter_ready_table_count"] = _int(
                summary.get("adapter_ready_table_count")
            )
            asset["adapter_missing_source_table_count"] = _int(
                summary.get("adapter_missing_source_table_count")
            )
            asset["template_dir_is_adapter_input_dir"] = bool(
                summary.get("template_dir_is_adapter_input_dir")
            )
            asset["production_readiness_claim"] = bool(
                payload.get("production_readiness_claim")
            )
        if payload.get("schema") == "uwm.production_governance_linkage_audit.v1":
            summary = payload.get("summary") or {}
            asset["linkage_audit_ready"] = bool(payload.get("linkage_audit_ready"))
            asset["all_required_tables_present"] = bool(
                payload.get("all_required_tables_present")
            )
            asset["governance_linkage_ready"] = bool(
                payload.get("governance_linkage_ready")
            )
            asset["planner_governance_binding_ready"] = bool(
                payload.get("planner_governance_binding_ready")
            )
            asset["expected_table_count"] = _int(
                summary.get("expected_table_count")
            )
            asset["present_table_count"] = _int(summary.get("present_table_count"))
            asset["missing_table_count"] = _int(summary.get("missing_table_count"))
            asset["policy_project_count"] = _int(
                summary.get("policy_project_count")
            )
            asset["linked_project_count"] = _int(
                summary.get("linked_project_count")
            )
            asset["unlinked_project_count"] = _int(
                summary.get("unlinked_project_count")
            )
            asset["production_readiness_claim"] = bool(
                payload.get("production_readiness_claim")
            )
        if (
            payload.get("schema")
            == "uwm.production_governance_planner_binding_gate.v1"
        ):
            summary = payload.get("summary") or {}
            asset["binding_gate_ready"] = bool(payload.get("binding_gate_ready"))
            asset["authoritative_governance_data_closure_ready"] = bool(
                payload.get("authoritative_governance_data_closure_ready")
            )
            asset["planner_governance_binding_ready"] = bool(
                payload.get("planner_governance_binding_ready")
            )
            asset["required_gate_count"] = _int(
                summary.get("required_gate_count")
            )
            asset["passed_gate_count"] = _int(summary.get("passed_gate_count"))
            asset["blocking_gate_count"] = _int(
                summary.get("blocking_gate_count")
            )
            asset["missing_table_count"] = _int(summary.get("missing_table_count"))
            asset["accepted_authoritative_row_count"] = _int(
                summary.get("accepted_authoritative_row_count")
            )
            asset["linked_project_count"] = _int(
                summary.get("linked_project_count")
            )
            asset["production_readiness_claim"] = bool(
                payload.get("production_readiness_claim")
            )
        if payload.get("schema") == "uwm.full_admin_livability_decision_package.v1":
            guard = payload.get("full_data_guard") or {}
            comparison = (
                payload.get("comparison_against_traditional_static_baselines") or {}
            )
            governance = payload.get("production_governance_binding_evidence") or {}
            asset["full_admin_decision_package_ready"] = bool(
                payload.get("full_admin_decision_package_ready")
            )
            asset["planner_governance_binding_ready"] = bool(
                payload.get("planner_governance_binding_ready")
            )
            asset["production_governance_binding_blocking_gate_count"] = _int(
                governance.get("blocking_gate_count")
            )
            asset["production_governance_binding_required_gate_count"] = _int(
                governance.get("required_gate_count")
            )
            asset["production_governance_binding_passed_gate_count"] = _int(
                governance.get("passed_gate_count")
            )
            asset["graph_node_count"] = _int(guard.get("graph_node_count"))
            asset["graph_edge_count"] = _int(guard.get("graph_edge_count"))
            asset["available_action_count"] = _int(
                guard.get("available_action_count")
            )
            asset["transition_count"] = _int(guard.get("transition_count"))
            asset["geographic_similarity_edge_count"] = _int(
                guard.get("geographic_similarity_edge_count")
            )
            asset["non_adjacent_similarity_edge_count"] = _int(
                guard.get("non_adjacent_similarity_edge_count")
            )
            asset["full_admin_decision_package_world_model_advantages_positive"] = bool(
                comparison.get("all_world_model_advantages_positive")
            )
            asset["planner_advantage_over_static"] = _float(
                comparison.get("planner_advantage_over_static")
            )
            asset["planner_risk_adjusted_advantage_over_static"] = _float(
                comparison.get("planner_risk_adjusted_advantage_over_static")
            )
            asset["graph_dqn_advantage_over_static"] = _float(
                comparison.get("graph_dqn_advantage_over_static")
            )
            asset["learned_rollout_advantage_over_static"] = _float(
                comparison.get("learned_rollout_advantage_over_static")
            )
        if (
            payload.get("schema")
            == "uwm.full_admin_energy_regularized_action_sequence_planner.v1"
        ):
            guard = payload.get("full_data_guard") or {}
            selected = payload.get("selected_sequence") or {}
            static = payload.get("traditional_static_baseline") or {}
            search = payload.get("search_config") or {}
            audit = payload.get("conservative_search_audit") or {}
            alignment = payload.get("search_value_alignment") or {}
            asset["full_admin_energy_regularized_planner_ready"] = bool(
                payload.get("full_admin_energy_regularized_planner_ready")
            )
            asset["graph_node_count"] = _int(guard.get("graph_node_count"))
            asset["graph_edge_count"] = _int(guard.get("graph_edge_count"))
            asset["available_action_count"] = _int(
                guard.get("available_action_count")
            )
            asset["geographic_similarity_edge_count"] = _int(
                guard.get("geographic_similarity_edge_count")
            )
            asset["non_adjacent_similarity_edge_count"] = _int(
                guard.get("non_adjacent_similarity_edge_count")
            )
            asset["evaluated_sequence_count"] = _int(
                search.get("evaluated_sequence_count")
            )
            asset["top_k_per_step"] = _int(search.get("top_k_per_step"))
            asset["advantage_over_traditional_static"] = _float(
                selected.get("advantage_over_traditional_static")
            )
            asset["selected_sequence_reward"] = _float(
                selected.get("raw_cumulative_reward")
            )
            asset["traditional_static_cumulative_reward"] = _float(
                static.get("cumulative_reward")
            )
            asset["planner_exploitation_guard_passed"] = bool(
                audit.get("planner_exploitation_guard_passed")
            )
            asset["search_value_alignment_ready"] = bool(
                alignment.get("search_value_alignment_ready")
            )
        if "graph_mdp_state" in payload:
            graph_statistics = (payload.get("graph_mdp_state") or {}).get(
                "graph_statistics"
            ) or {}
            asset["graph_node_count"] = _int(graph_statistics.get("node_count"))
            asset["graph_edge_count"] = _int(graph_statistics.get("edge_count"))
            asset["available_action_count"] = _int(
                graph_statistics.get("available_action_count")
            )
        if "source_geographic_similarity_kernel_summary" in payload:
            similarity_summary = (
                payload.get("source_geographic_similarity_kernel_summary") or {}
            )
            asset["geographic_similarity_edge_count"] = _int(
                similarity_summary.get("similarity_edge_count")
            )
            asset["non_adjacent_similarity_edge_count"] = _int(
                similarity_summary.get("non_adjacent_similarity_edge_count")
            )
        if "trajectory_dataset" in payload:
            trajectory = payload.get("trajectory_dataset") or {}
            asset["transition_count"] = _int(trajectory.get("transition_count"))
        if "search_config" in payload:
            search_config = payload.get("search_config") or {}
            asset["transition_storage"] = search_config.get("transition_storage")
        if "observed_policy_outcome_superiority_claim" in payload:
            asset["observed_policy_outcome_superiority_claim"] = bool(
                payload.get("observed_policy_outcome_superiority_claim")
            )
        if "supported_claim" in payload:
            asset["supported_claim"] = payload.get("supported_claim")
        if "training_summary" in payload:
            training = payload.get("training_summary") or {}
            asset["training_episode_count"] = _int(training.get("episode_count"))
            asset["training_sample_count"] = _int(
                training.get("training_sample_count")
            )
            asset["transition_count"] = _int(
                training.get("transition_count"),
                default=_int(asset.get("transition_count")),
            )
            asset["real_data_graph_node_count"] = _int(
                training.get("real_data_graph_node_count")
            )
            asset["real_data_graph_edge_count"] = _int(
                training.get("real_data_graph_edge_count")
            )
            asset["real_data_available_action_count"] = _int(
                training.get("real_data_available_action_count")
            )
            asset["source_graph_node_count"] = _int(
                training.get("source_graph_node_count")
            )
            asset["source_graph_edge_count"] = _int(
                training.get("source_graph_edge_count")
            )
            asset["source_available_action_count"] = _int(
                training.get("source_available_action_count")
            )
            asset["exhaustive_action_pair_training"] = bool(
                training.get("exhaustive_action_pair_training")
            )
            asset["sampled_first_action_count"] = _int(
                training.get("sampled_first_action_count")
            )
            asset["sampled_second_action_limit"] = _int(
                training.get("sampled_second_action_limit")
            )
        if "learned_policy_evaluation" in payload:
            learned = payload.get("learned_policy_evaluation") or {}
            asset["advantage_over_traditional_static"] = _float(
                learned.get("advantage_over_traditional_static")
            )
            asset["graph_dqn_policy_cumulative_reward"] = _float(
                learned.get("graph_dqn_policy_cumulative_reward")
            )
            asset["policy_action_scope"] = learned.get("policy_action_scope")
        if "holdout_metrics" in payload:
            holdout = payload.get("holdout_metrics") or {}
            asset["reward_mae"] = _float(holdout.get("reward_mae"))
            asset["dynamics_mae_by_target"] = holdout.get("dynamics_mae_by_target") or {}
        if "baseline_metrics" in payload:
            baseline = payload.get("baseline_metrics") or {}
            asset["train_mean_reward_mae"] = _float(
                baseline.get("train_mean_reward_mae")
            )
            asset["train_mean_mae_by_target"] = (
                baseline.get("train_mean_mae_by_target") or {}
            )
        if "learned_rollout_planner" in payload:
            planner = payload.get("learned_rollout_planner") or {}
            asset["imagined_advantage_over_static_single_step"] = _float(
                planner.get("imagined_advantage_over_static_single_step")
            )
            asset["imagined_advantage_over_one_step_policy"] = _float(
                planner.get("imagined_advantage_over_one_step_policy")
            )
        if "rl_algorithm" in payload:
            asset["rl_algorithm"] = (payload.get("rl_algorithm") or {}).get(
                "algorithm"
            )
        if "drl_algorithm" in payload:
            drl_algorithm = payload.get("drl_algorithm") or {}
            asset["drl_algorithm"] = drl_algorithm.get("algorithm")
            asset["is_deep_rl"] = bool(drl_algorithm.get("is_deep_rl"))
            asset["uses_graph_message_passing"] = bool(
                drl_algorithm.get("uses_graph_message_passing")
            )
            asset["policy_or_value_network_trained"] = bool(
                drl_algorithm.get("policy_or_value_network_trained")
            )
        if "planner_algorithm" in payload:
            planner_algorithm = payload.get("planner_algorithm") or {}
            search_config = payload.get("search_config") or {}
            audit = payload.get("conservative_search_audit") or {}
            alignment = payload.get("search_value_alignment") or {}
            selected = payload.get("selected_sequence") or {}
            asset["planner_algorithm"] = planner_algorithm.get("algorithm")
            asset["is_model_based"] = bool(planner_algorithm.get("is_model_based"))
            asset["uses_behavior_prior_energy"] = bool(
                planner_algorithm.get("uses_behavior_prior_energy")
            )
            asset["uses_ood_action_drift_guard"] = bool(
                planner_algorithm.get("uses_ood_action_drift_guard")
            )
            asset["evaluated_sequence_count"] = _int(
                search_config.get("evaluated_sequence_count")
            )
            asset["planner_exploitation_guard_passed"] = bool(
                audit.get("planner_exploitation_guard_passed")
            )
            asset["search_value_alignment_ready"] = bool(
                alignment.get("search_value_alignment_ready")
            )
            asset["advantage_over_traditional_static"] = _float(
                selected.get("advantage_over_traditional_static")
            )
    return asset


def _data_agent_catalog_integration(
    *,
    assets: list[dict[str, Any]],
    lineage_edges: list[dict[str, str]],
    catalog_id: str,
    created_at: str,
) -> dict[str, Any]:
    registration_assets = [
        _data_agent_asset_registration_spec(asset, catalog_id, created_at)
        for asset in assets
    ]
    registration_edges = [
        _data_agent_lineage_registration_spec(edge, catalog_id)
        for edge in lineage_edges
    ]
    return {
        "source_of_truth_table": "agent_data_assets",
        "lineage_table": "agent_asset_lineage",
        "shadow_catalog": False,
        "integration_mode": "scene_projection_over_existing_data_catalog",
        "reuse_existing_api_routes": [
            "/api/catalog",
            "/api/catalog/search",
            "/api/catalog/{id}/lineage",
            "/api/catalog/{id}/cross-system-lineage",
            "/api/metadata/search",
        ],
        "reuse_existing_modules": [
            "data_agent.data_catalog",
            "data_agent.metadata_manager",
            "data_agent.api.lineage_routes",
            "data_agent.fusion.lakehouse_publisher",
            "data_agent.fusion.semantic_publisher",
            "data_agent.uwm.mmfe_state_input",
        ],
        "registration_plan": {
            "schema": "uwm.livability_data_agent_catalog_registration_plan.v1",
            "catalog_id": catalog_id,
            "created_at": created_at,
            "asset_count": len(registration_assets),
            "lineage_edge_count": len(registration_edges),
            "assets": registration_assets,
            "lineage_edges": registration_edges,
        },
    }


def _full_data_readiness(
    full_admin_service_surface_asset: dict[str, Any],
    full_admin_service_quality_asset: dict[str, Any],
    geographic_similarity_asset: dict[str, Any],
    full_admin_planner_asset: dict[str, Any],
    full_admin_graph_drl_asset: dict[str, Any],
    full_admin_learned_rollout_asset: dict[str, Any],
    full_admin_decision_package_asset: dict[str, Any],
    full_admin_action_inventory_asset: dict[str, Any],
    full_admin_energy_planner_asset: dict[str, Any],
) -> dict[str, Any]:
    service_surface_completed = (
        full_admin_service_surface_asset.get("exists") is True
        and full_admin_service_surface_asset.get("schema")
        == "uwm.full_admin_service_accessibility_surface.v1"
        and _int(full_admin_service_surface_asset.get("admin_unit_count")) == 1017
        and _int(full_admin_service_surface_asset.get("source_poi_point_count"))
        == 1194351
        and _int(full_admin_service_surface_asset.get("source_road_count")) == 50366
        and _int(full_admin_service_surface_asset.get("service_missing_admin_count"))
        == 0
        and _int(
            full_admin_service_surface_asset.get(
                "admin_units_with_accessibility_score"
            )
        )
        == 1017
        and full_admin_service_surface_asset.get("supported_claim")
        == "full_admin_service_accessibility_surface_covers_all_admin_units_from_local_poi_and_road_assets"
        and full_admin_service_surface_asset.get(
            "observed_policy_outcome_superiority_claim"
        )
        is False
    )
    service_quality_completed = (
        full_admin_service_quality_asset.get("exists") is True
        and full_admin_service_quality_asset.get("schema")
        == "uwm.full_admin_service_surface_quality_audit.v1"
        and _int(full_admin_service_quality_asset.get("admin_unit_count")) == 1017
        and _int(full_admin_service_quality_asset.get("endpoint_count")) == 2
        and _int(full_admin_service_quality_asset.get("ready_endpoint_count")) == 2
        and full_admin_service_quality_asset.get(
            "full_admin_service_surface_quality_audit_ready"
        )
        is True
        and full_admin_service_quality_asset.get("supported_claim")
        == "full_admin_service_surface_proxy_quality_beats_static_and_negative_controls"
        and full_admin_service_quality_asset.get(
            "observed_policy_outcome_superiority_claim"
        )
        is False
    )
    geographic_similarity_completed = (
        geographic_similarity_asset.get("exists") is True
        and geographic_similarity_asset.get("schema")
        == "uwm.geographic_similarity_kernel.v1"
        and geographic_similarity_asset.get("geographic_similarity_kernel_ready")
        is True
        and _int(geographic_similarity_asset.get("panel_unit_count")) == 1017
        and _int(geographic_similarity_asset.get("similarity_edge_count")) == 5085
        and _int(geographic_similarity_asset.get("non_adjacent_similarity_edge_count"))
        == 4835
        and geographic_similarity_asset.get(
            "rotated_target_similarity_control_passed"
        )
        is True
        and geographic_similarity_asset.get(
            "observed_policy_outcome_superiority_claim"
        )
        is False
    )
    action_inventory_completed = (
        full_admin_action_inventory_asset.get("exists") is True
        and full_admin_action_inventory_asset.get("schema")
        == "uwm.full_admin_action_inventory.v1"
        and full_admin_action_inventory_asset.get("experiment_scope")
        == "full_admin_graph"
        and full_admin_action_inventory_asset.get("full_data_guard_passed") is True
        and _int(full_admin_action_inventory_asset.get("graph_node_count")) == 1017
        and _int(full_admin_action_inventory_asset.get("graph_edge_count")) == 7932
        and _int(full_admin_action_inventory_asset.get("available_action_count"))
        == 1137
        and full_admin_action_inventory_asset.get("action_type_counts")
        == {
            "increase_green_infrastructure": 81,
            "traffic_emission_control": 77,
            "add_community_service": 979,
        }
        and full_admin_action_inventory_asset.get(
            "observed_policy_outcome_superiority_claim"
        )
        is False
    )
    planner_completed = (
        full_admin_planner_asset.get("exists") is True
        and full_admin_planner_asset.get("schema")
        == "uwm.model_based_graph_search_report.v1"
        and full_admin_planner_asset.get("experiment_scope") == "full_admin_graph"
        and full_admin_planner_asset.get("full_data_guard_passed") is True
        and _int(full_admin_planner_asset.get("graph_node_count")) == 1017
        and _int(full_admin_planner_asset.get("graph_edge_count")) == 7932
        and _int(full_admin_planner_asset.get("geographic_similarity_edge_count"))
        == 5085
        and _int(full_admin_planner_asset.get("available_action_count")) > 60
        and full_admin_planner_asset.get("transition_storage") == "compact"
    )
    graph_drl_completed = (
        full_admin_graph_drl_asset.get("exists") is True
        and full_admin_graph_drl_asset.get("schema")
        == "uwm.livability_graph_drl_training_report.v1"
        and full_admin_graph_drl_asset.get("experiment_scope") == "full_admin_graph"
        and full_admin_graph_drl_asset.get("full_data_guard_passed") is True
        and _int(full_admin_graph_drl_asset.get("real_data_graph_node_count")) == 1017
        and _int(full_admin_graph_drl_asset.get("real_data_graph_edge_count")) == 7932
        and _int(full_admin_graph_drl_asset.get("geographic_similarity_edge_count"))
        == 5085
        and _int(full_admin_graph_drl_asset.get("real_data_available_action_count"))
        > 60
        and _int(full_admin_graph_drl_asset.get("training_sample_count")) > 0
        and _float(
            full_admin_graph_drl_asset.get("advantage_over_traditional_static")
        )
        > 0.0
        and full_admin_graph_drl_asset.get("supported_claim")
        == "graph_dqn_value_network_improves_same_scene_static_livability_baseline"
    )
    learned_rollout_completed = (
        full_admin_learned_rollout_asset.get("exists") is True
        and full_admin_learned_rollout_asset.get("schema")
        == "uwm.offline_world_model_rollout_planner_report.v1"
        and full_admin_learned_rollout_asset.get("experiment_scope")
        == "full_admin_graph"
        and full_admin_learned_rollout_asset.get("full_data_guard_passed") is True
        and _int(full_admin_learned_rollout_asset.get("source_graph_node_count"))
        == 1017
        and _int(full_admin_learned_rollout_asset.get("source_graph_edge_count"))
        == _int(full_admin_planner_asset.get("graph_edge_count"))
        and _int(
            full_admin_learned_rollout_asset.get("source_available_action_count")
        )
        == _int(full_admin_planner_asset.get("available_action_count"))
        and _int(full_admin_learned_rollout_asset.get("transition_count"))
        == _int(full_admin_planner_asset.get("transition_count"))
        and _float(full_admin_learned_rollout_asset.get("reward_mae"))
        < _float(full_admin_learned_rollout_asset.get("train_mean_reward_mae"))
        and _float(
            full_admin_learned_rollout_asset.get(
                "imagined_advantage_over_static_single_step"
            )
        )
        > 0.0
        and _float(
            full_admin_learned_rollout_asset.get(
                "imagined_advantage_over_one_step_policy"
            )
        )
        > 0.0
        and full_admin_learned_rollout_asset.get("supported_claim")
        == "full_admin_graph_learned_world_model_rollout_improves_imagined_static_and_one_step_baselines"
        and full_admin_learned_rollout_asset.get(
            "observed_policy_outcome_superiority_claim"
        )
        is False
    )
    decision_package_completed = (
        full_admin_decision_package_asset.get("exists") is True
        and full_admin_decision_package_asset.get("schema")
        == "uwm.full_admin_livability_decision_package.v1"
        and full_admin_decision_package_asset.get("experiment_scope")
        == "full_admin_graph"
        and full_admin_decision_package_asset.get("full_data_guard_passed") is True
        and full_admin_decision_package_asset.get(
            "full_admin_decision_package_ready"
        )
        is True
        and _int(full_admin_decision_package_asset.get("graph_node_count")) == 1017
        and _int(full_admin_decision_package_asset.get("graph_edge_count")) == 7932
        and _int(full_admin_decision_package_asset.get("available_action_count"))
        == _int(full_admin_planner_asset.get("available_action_count"))
        and _int(full_admin_decision_package_asset.get("transition_count"))
        == _int(full_admin_planner_asset.get("transition_count"))
        and _int(
            full_admin_decision_package_asset.get(
                "geographic_similarity_edge_count"
            )
        )
        == 5085
        and full_admin_decision_package_asset.get(
            "full_admin_decision_package_world_model_advantages_positive"
        )
        is True
        and full_admin_decision_package_asset.get(
            "observed_policy_outcome_superiority_claim"
        )
        is False
    )
    full_admin_energy_planner_completed = (
        full_admin_energy_planner_asset.get("exists") is True
        and full_admin_energy_planner_asset.get("schema")
        == "uwm.full_admin_energy_regularized_action_sequence_planner.v1"
        and full_admin_energy_planner_asset.get("experiment_scope")
        == "full_admin_graph"
        and full_admin_energy_planner_asset.get("full_data_guard_passed") is True
        and full_admin_energy_planner_asset.get(
            "full_admin_energy_regularized_planner_ready"
        )
        is True
        and _int(full_admin_energy_planner_asset.get("graph_node_count")) == 1017
        and _int(full_admin_energy_planner_asset.get("graph_edge_count")) == 7932
        and _int(full_admin_energy_planner_asset.get("available_action_count"))
        == 1137
        and _int(
            full_admin_energy_planner_asset.get("geographic_similarity_edge_count")
        )
        == 5085
        and _float(
            full_admin_energy_planner_asset.get(
                "advantage_over_traditional_static"
            )
        )
        > 0.0
        and full_admin_energy_planner_asset.get(
            "planner_exploitation_guard_passed"
        )
        is True
        and full_admin_energy_planner_asset.get("search_value_alignment_ready")
        is True
        and full_admin_energy_planner_asset.get(
            "observed_policy_outcome_superiority_claim"
        )
        is False
    )
    return {
        "full_admin_service_accessibility_surface_completed": service_surface_completed,
        "full_admin_service_surface_admin_unit_count": _int(
            full_admin_service_surface_asset.get("admin_unit_count")
        ),
        "full_admin_service_surface_poi_point_count": _int(
            full_admin_service_surface_asset.get("source_poi_point_count")
        ),
        "full_admin_service_surface_road_count": _int(
            full_admin_service_surface_asset.get("source_road_count")
        ),
        "full_admin_service_surface_missing_admin_count": _int(
            full_admin_service_surface_asset.get("service_missing_admin_count")
        ),
        "full_admin_service_surface_accessibility_score_count": _int(
            full_admin_service_surface_asset.get(
                "admin_units_with_accessibility_score"
            )
        ),
        "full_admin_service_surface_total_service_point_count": _int(
            full_admin_service_surface_asset.get("total_service_point_count")
        ),
        "full_admin_service_surface_total_essential_service_count": _int(
            full_admin_service_surface_asset.get("total_essential_service_count")
        ),
        "full_admin_service_surface_quality_audit_completed": service_quality_completed,
        "full_admin_service_surface_quality_endpoint_count": _int(
            full_admin_service_quality_asset.get("endpoint_count")
        ),
        "full_admin_service_surface_quality_ready_endpoint_count": _int(
            full_admin_service_quality_asset.get("ready_endpoint_count")
        ),
        "geographic_similarity_kernel_completed": geographic_similarity_completed,
        "geographic_similarity_panel_unit_count": _int(
            geographic_similarity_asset.get("panel_unit_count")
        ),
        "geographic_similarity_edge_count": _int(
            geographic_similarity_asset.get("similarity_edge_count")
        ),
        "geographic_similarity_non_adjacent_edge_count": _int(
            geographic_similarity_asset.get("non_adjacent_similarity_edge_count")
        ),
        "geographic_similarity_rotated_control_passed": bool(
            geographic_similarity_asset.get("rotated_target_similarity_control_passed")
        ),
        "full_admin_action_inventory_completed": action_inventory_completed,
        "full_admin_action_inventory_node_count": _int(
            full_admin_action_inventory_asset.get("graph_node_count")
        ),
        "full_admin_action_inventory_edge_count": _int(
            full_admin_action_inventory_asset.get("graph_edge_count")
        ),
        "full_admin_action_inventory_action_count": _int(
            full_admin_action_inventory_asset.get("available_action_count")
        ),
        "full_admin_action_inventory_action_type_counts": dict(
            full_admin_action_inventory_asset.get("action_type_counts") or {}
        ),
        "full_admin_graph_planner_replay_completed": planner_completed,
        "full_admin_graph_node_count": _int(
            full_admin_planner_asset.get("graph_node_count")
        ),
        "full_admin_graph_edge_count": _int(
            full_admin_planner_asset.get("graph_edge_count")
        ),
        "full_admin_available_action_count": _int(
            full_admin_planner_asset.get("available_action_count")
        ),
        "full_admin_transition_count": _int(
            full_admin_planner_asset.get("transition_count")
        ),
        "transition_storage": full_admin_planner_asset.get("transition_storage"),
        "full_admin_graph_drl_training_completed": graph_drl_completed,
        "full_admin_graph_drl_node_count": _int(
            full_admin_graph_drl_asset.get("real_data_graph_node_count")
        ),
        "full_admin_graph_drl_edge_count": _int(
            full_admin_graph_drl_asset.get("real_data_graph_edge_count")
        ),
        "full_admin_graph_drl_available_action_count": _int(
            full_admin_graph_drl_asset.get("real_data_available_action_count")
        ),
        "full_admin_graph_drl_training_sample_count": _int(
            full_admin_graph_drl_asset.get("training_sample_count")
        ),
        "full_admin_graph_drl_sampled_first_action_count": _int(
            full_admin_graph_drl_asset.get("sampled_first_action_count")
        ),
        "full_admin_graph_drl_sampled_second_action_limit": _int(
            full_admin_graph_drl_asset.get("sampled_second_action_limit")
        ),
        "full_admin_graph_drl_advantage_over_traditional_static": _float(
            full_admin_graph_drl_asset.get("advantage_over_traditional_static")
        ),
        "full_admin_learned_world_model_rollout_completed": learned_rollout_completed,
        "full_admin_learned_world_model_rollout_transition_count": _int(
            full_admin_learned_rollout_asset.get("transition_count")
        ),
        "full_admin_learned_world_model_rollout_node_count": _int(
            full_admin_learned_rollout_asset.get("source_graph_node_count")
        ),
        "full_admin_learned_world_model_rollout_available_action_count": _int(
            full_admin_learned_rollout_asset.get("source_available_action_count")
        ),
        "full_admin_learned_world_model_rollout_reward_mae": _float(
            full_admin_learned_rollout_asset.get("reward_mae")
        ),
        "full_admin_learned_world_model_rollout_train_mean_reward_mae": _float(
            full_admin_learned_rollout_asset.get("train_mean_reward_mae")
        ),
        "full_admin_learned_world_model_rollout_advantage_over_static": _float(
            full_admin_learned_rollout_asset.get(
                "imagined_advantage_over_static_single_step"
            )
        ),
        "full_admin_learned_world_model_rollout_advantage_over_one_step": _float(
            full_admin_learned_rollout_asset.get(
                "imagined_advantage_over_one_step_policy"
            )
        ),
        "full_admin_livability_decision_package_completed": decision_package_completed,
        "full_admin_decision_package_graph_node_count": _int(
            full_admin_decision_package_asset.get("graph_node_count")
        ),
        "full_admin_decision_package_graph_edge_count": _int(
            full_admin_decision_package_asset.get("graph_edge_count")
        ),
        "full_admin_decision_package_transition_count": _int(
            full_admin_decision_package_asset.get("transition_count")
        ),
        "full_admin_decision_package_world_model_advantages_positive": bool(
            full_admin_decision_package_asset.get(
                "full_admin_decision_package_world_model_advantages_positive"
            )
        ),
        "full_admin_decision_package_planner_advantage_over_static": _float(
            full_admin_decision_package_asset.get("planner_advantage_over_static")
        ),
        "full_admin_decision_package_graph_dqn_advantage_over_static": _float(
            full_admin_decision_package_asset.get("graph_dqn_advantage_over_static")
        ),
        "full_admin_decision_package_learned_rollout_advantage_over_static": _float(
            full_admin_decision_package_asset.get(
                "learned_rollout_advantage_over_static"
            )
        ),
        "full_admin_energy_regularized_planner_completed": (
            full_admin_energy_planner_completed
        ),
        "full_admin_energy_regularized_planner_graph_node_count": _int(
            full_admin_energy_planner_asset.get("graph_node_count")
        ),
        "full_admin_energy_regularized_planner_graph_edge_count": _int(
            full_admin_energy_planner_asset.get("graph_edge_count")
        ),
        "full_admin_energy_regularized_planner_available_action_count": _int(
            full_admin_energy_planner_asset.get("available_action_count")
        ),
        "full_admin_energy_regularized_planner_evaluated_sequence_count": _int(
            full_admin_energy_planner_asset.get("evaluated_sequence_count")
        ),
        "full_admin_energy_regularized_planner_advantage_over_static": _float(
            full_admin_energy_planner_asset.get(
                "advantage_over_traditional_static"
            )
        ),
        "claim_boundary": (
            "full_admin_graph_decision_and_conservative_planner_not_observed_policy_outcome"
            if decision_package_completed and full_admin_energy_planner_completed
            else "full_admin_graph_decision_package_not_observed_policy_outcome"
            if decision_package_completed
            else "full_admin_graph_planner_graph_drl_and_learned_rollout_not_observed_policy_outcome"
            if planner_completed and graph_drl_completed and learned_rollout_completed
            else "full_admin_graph_planner_and_graph_drl_not_observed_policy_outcome"
            if planner_completed and graph_drl_completed
            else "full_admin_graph_partial_readiness_not_observed_policy_outcome"
            if planner_completed or graph_drl_completed or learned_rollout_completed
            else "full_admin_graph_planner_replay_not_ready"
        ),
    }


def _data_agent_asset_registration_spec(
    asset: dict[str, Any],
    catalog_id: str,
    created_at: str,
) -> dict[str, Any]:
    uwm_asset_id = str(asset.get("asset_id") or "")
    role = str(asset.get("role") or "")
    stage = str(asset.get("stage") or "")
    fmt = str(asset.get("format") or "")
    keywords = [
        "uwm_livability",
        "urban_livability",
        stage,
        role,
    ]
    if str(asset.get("mmfe_status") or "").startswith("mmfe_state_input"):
        keywords.append("mmfe_state_input")
    return {
        "target_table": "agent_data_assets",
        "uwm_asset_id": uwm_asset_id,
        "asset_name": f"uwm_livability__{uwm_asset_id}",
        "display_name": f"UWM Livability - {role or uwm_asset_id}",
        "exists": bool(asset.get("exists")),
        "technical": {
            "storage": {
                "backend": "local",
                "path": asset.get("path") or "",
                "format": fmt,
                "size_bytes": _int(asset.get("size_bytes")),
            },
            "structure": {
                "schema": asset.get("schema") or "",
                "feature_count": _int(asset.get("admin_unit_count")),
            },
            "uwm": {
                "asset_id": uwm_asset_id,
                "role": role,
                "stage": stage,
                "relative_path": asset.get("relative_path") or "",
                "mmfe_status": asset.get("mmfe_status") or "",
            },
        },
        "business": {
            "semantic": {
                "description": (
                    f"UWM urban livability {role or uwm_asset_id} asset "
                    "projected into the GIS Data Agent unified catalog."
                ),
                "keywords": [item for item in keywords if item],
            },
            "classification": {
                "category": _catalog_category(fmt),
                "domain": "urban_livability",
                "scenario": "chongqing_central_livability",
            },
        },
        "operational": {
            "source": {
                "type": "local_uwm_public_proxy",
                "uri": asset.get("path") or "",
            },
            "creation": {
                "tool": "uwm_livability_pipeline",
                "pipeline_run_id": catalog_id,
                "created_at": created_at,
                "params": {
                    "uwm_asset_id": uwm_asset_id,
                    "role": role,
                    "stage": stage,
                },
            },
            "version": {
                "version": 1,
                "is_latest": True,
            },
        },
        "lineage": {
            "upstream": {"asset_ids": []},
            "uwm_scene": {
                "catalog_id": catalog_id,
                "asset_id": uwm_asset_id,
                "stage": stage,
            },
        },
    }


def _data_agent_lineage_registration_spec(
    edge: dict[str, str],
    catalog_id: str,
) -> dict[str, str]:
    return {
        "target_table": "agent_asset_lineage",
        "source_asset_key": edge["from"],
        "target_asset_key": edge["to"],
        "relationship": edge["relation"],
        "pipeline_run_id": catalog_id,
    }


def _catalog_category(fmt: str) -> str:
    if fmt == "geojson":
        return "vector"
    if fmt in {"tif", "tiff", "cog"}:
        return "raster"
    if fmt in {"csv", "xlsx", "xls"}:
        return "tabular"
    if fmt == "json":
        return "other"
    return fmt or "other"


def _mmfe_state_input_assets(root: Path) -> list[dict[str, Any]]:
    paths = sorted(root.glob("**/mmfe_uwm_state_input_*.json"))
    assets = []
    for index, path in enumerate(paths, start=1):
        payload = _read_json_if_possible(path)
        asset_id = f"mmfe_state_input_{index:02d}_{path.stem.removeprefix('mmfe_uwm_state_input_')}"
        assets.append(
            {
                "asset_id": asset_id,
                "role": "mmfe_state_input_artifact",
                "stage": "mmfe_state_input",
                "format": "json",
                "path": str(path),
                "relative_path": str(path.relative_to(root)),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "schema": payload.get("schema"),
                "mmfe_status": "mmfe_state_input_available_not_full_managed_pipeline",
            }
        )
    return assets


def _lineage_edges() -> list[dict[str, str]]:
    return [
        {
            "from": "admin_units_geojson",
            "to": "multisource_livability_scene",
            "relation": "admin_geometry_alignment",
        },
        {
            "from": "multisource_livability_scene",
            "to": "livability_endpoint_suite",
            "relation": "endpoint_validation_input",
        },
        {
            "from": "building_floor_morphology",
            "to": "livability_endpoint_suite",
            "relation": "endpoint_25d_morphology_input",
        },
        {
            "from": "data_calibrated_mechanism_table",
            "to": "data_calibrated_planner_replay",
            "relation": "simulator_mechanism_input",
        },
        {
            "from": "full_admin_livability_target_panel",
            "to": "full_admin_graph_planner_replay",
            "relation": "full_admin_graph_state_input",
        },
        {
            "from": "geographic_similarity_kernel",
            "to": "full_admin_graph_planner_replay",
            "relation": "full_admin_graph_similarity_edge_input",
        },
        {
            "from": "full_admin_data_calibrated_mechanism_table",
            "to": "full_admin_graph_planner_replay",
            "relation": "full_admin_simulator_mechanism_input",
        },
        {
            "from": "admin_units_geojson",
            "to": "full_admin_service_accessibility_surface",
            "relation": "full_admin_service_surface_admin_geometry_input",
        },
        {
            "from": "local_planning_zip_inventory",
            "to": "full_admin_service_accessibility_surface",
            "relation": "full_admin_service_surface_local_poi_road_source_inventory",
        },
        {
            "from": "full_admin_service_accessibility_surface",
            "to": "full_admin_service_surface_quality_audit",
            "relation": "full_admin_service_surface_quality_input",
        },
        {
            "from": "full_admin_service_surface_quality_audit",
            "to": "full_admin_livability_target_panel",
            "relation": "full_admin_service_quality_evidence_input",
        },
        {
            "from": "full_admin_service_accessibility_surface",
            "to": "full_admin_livability_target_panel",
            "relation": "full_admin_service_state_input",
        },
        {
            "from": "admin_units_geojson",
            "to": "full_admin_graph_planner_replay",
            "relation": "full_admin_boundary_graph_input",
        },
        {
            "from": "full_admin_livability_target_panel",
            "to": "full_admin_graph_drl_training_report",
            "relation": "full_admin_graph_drl_state_input",
        },
        {
            "from": "full_admin_data_calibrated_mechanism_table",
            "to": "full_admin_graph_drl_training_report",
            "relation": "full_admin_graph_drl_mechanism_input",
        },
        {
            "from": "admin_units_geojson",
            "to": "full_admin_graph_drl_training_report",
            "relation": "full_admin_graph_drl_boundary_graph_input",
        },
        {
            "from": "geographic_similarity_kernel",
            "to": "full_admin_graph_drl_training_report",
            "relation": "full_admin_graph_drl_similarity_edge_input",
        },
        {
            "from": "full_admin_graph_planner_replay",
            "to": "full_admin_learned_world_model_rollout",
            "relation": "full_admin_compact_replay_training_input",
        },
        {
            "from": "full_admin_livability_target_panel",
            "to": "full_admin_action_inventory",
            "relation": "full_admin_action_inventory_state_input",
        },
        {
            "from": "geographic_similarity_kernel",
            "to": "full_admin_action_inventory",
            "relation": "full_admin_action_inventory_similarity_edge_input",
        },
        {
            "from": "full_admin_action_inventory",
            "to": "full_admin_energy_regularized_planner_report",
            "relation": "full_admin_energy_planner_feasible_action_inventory_input",
        },
        {
            "from": "full_admin_action_inventory",
            "to": "production_state_action_space_assessment",
            "relation": "production_assessment_current_action_space_input",
        },
        {
            "from": "full_admin_livability_decision_package",
            "to": "production_state_action_space_assessment",
            "relation": "production_assessment_current_full_admin_scope_input",
        },
        {
            "from": "local_planning_zip_inventory",
            "to": "production_state_action_space_assessment",
            "relation": "production_assessment_local_asset_scope_input",
        },
        {
            "from": "production_state_action_space_assessment",
            "to": "production_action_catalog",
            "relation": "production_action_catalog_target_ontology_input",
        },
        {
            "from": "full_admin_action_inventory",
            "to": "production_action_catalog",
            "relation": "production_action_catalog_current_feasible_binding_input",
        },
        {
            "from": "production_action_catalog",
            "to": "production_governance_data_contract",
            "relation": "governance_contract_action_catalog_input",
        },
        {
            "from": "local_planning_zip_inventory",
            "to": "production_governance_data_contract",
            "relation": "governance_contract_local_planning_sample_scope_input",
        },
        {
            "from": "production_governance_data_contract",
            "to": "production_governance_data_adapter_readiness",
            "relation": "governance_adapter_contract_input",
        },
        {
            "from": "production_governance_data_contract",
            "to": "production_governance_input_templates",
            "relation": "governance_input_templates_contract_input",
        },
        {
            "from": "production_governance_data_adapter_readiness",
            "to": "production_governance_input_templates",
            "relation": "governance_input_templates_readiness_boundary_input",
        },
        {
            "from": "production_governance_data_adapter_readiness",
            "to": "production_governance_linkage_audit",
            "relation": "governance_linkage_adapter_readiness_input",
        },
        {
            "from": "production_governance_input_templates",
            "to": "production_governance_linkage_audit",
            "relation": "governance_linkage_expected_table_contract_input",
        },
        {
            "from": "production_action_catalog",
            "to": "production_governance_planner_binding_gate",
            "relation": "planner_binding_gate_action_contract_input",
        },
        {
            "from": "production_governance_data_contract",
            "to": "production_governance_planner_binding_gate",
            "relation": "planner_binding_gate_governance_contract_input",
        },
        {
            "from": "production_governance_data_adapter_readiness",
            "to": "production_governance_planner_binding_gate",
            "relation": "planner_binding_gate_adapter_readiness_input",
        },
        {
            "from": "production_governance_linkage_audit",
            "to": "production_governance_planner_binding_gate",
            "relation": "planner_binding_gate_linkage_audit_input",
        },
        {
            "from": "full_admin_livability_target_panel",
            "to": "full_admin_energy_regularized_planner_report",
            "relation": "full_admin_energy_planner_state_input",
        },
        {
            "from": "full_admin_data_calibrated_mechanism_table",
            "to": "full_admin_energy_regularized_planner_report",
            "relation": "full_admin_energy_planner_mechanism_input",
        },
        {
            "from": "geographic_similarity_kernel",
            "to": "full_admin_energy_regularized_planner_report",
            "relation": "full_admin_energy_planner_similarity_edge_input",
        },
        {
            "from": "full_admin_graph_drl_training_report",
            "to": "full_admin_energy_regularized_planner_report",
            "relation": "full_admin_energy_planner_search_value_alignment_input",
        },
        {
            "from": "full_admin_graph_planner_replay",
            "to": "full_admin_livability_decision_package",
            "relation": "full_admin_decision_planner_replay_input",
        },
        {
            "from": "full_admin_graph_drl_training_report",
            "to": "full_admin_livability_decision_package",
            "relation": "full_admin_decision_graph_dqn_input",
        },
        {
            "from": "full_admin_learned_world_model_rollout",
            "to": "full_admin_livability_decision_package",
            "relation": "full_admin_decision_learned_rollout_input",
        },
        {
            "from": "geographic_similarity_kernel",
            "to": "full_admin_livability_decision_package",
            "relation": "full_admin_decision_similarity_kernel_input",
        },
        {
            "from": "full_admin_service_accessibility_surface",
            "to": "full_admin_livability_decision_package",
            "relation": "full_admin_decision_service_surface_input",
        },
        {
            "from": "full_admin_service_surface_quality_audit",
            "to": "full_admin_livability_decision_package",
            "relation": "full_admin_decision_service_quality_input",
        },
        {
            "from": "production_governance_planner_binding_gate",
            "to": "full_admin_livability_decision_package",
            "relation": "full_admin_decision_production_governance_binding_gate_input",
        },
        {
            "from": "admin_units_geojson",
            "to": "data_calibrated_spatial_spillover_kernel",
            "relation": "admin_boundary_adjacency_input",
        },
        {
            "from": "multisource_livability_scene",
            "to": "data_calibrated_spatial_spillover_kernel",
            "relation": "admin_livability_need_input",
        },
        {
            "from": "multisource_livability_scene",
            "to": "data_calibrated_planner_replay",
            "relation": "planner_state_input",
        },
        {
            "from": "multisource_livability_scene",
            "to": "livability_rl_training_report",
            "relation": "rl_training_graph_mdp_state_input",
        },
        {
            "from": "data_calibrated_mechanism_table",
            "to": "livability_rl_training_report",
            "relation": "rl_training_mechanism_input",
        },
        {
            "from": "data_calibrated_spatial_spillover_kernel",
            "to": "livability_rl_training_report",
            "relation": "rl_training_spatial_spillover_input",
        },
        {
            "from": "multisource_livability_scene",
            "to": "livability_graph_drl_training_report",
            "relation": "graph_drl_graph_mdp_state_input",
        },
        {
            "from": "data_calibrated_mechanism_table",
            "to": "livability_graph_drl_training_report",
            "relation": "graph_drl_mechanism_input",
        },
        {
            "from": "data_calibrated_spatial_spillover_kernel",
            "to": "livability_graph_drl_training_report",
            "relation": "graph_drl_spatial_spillover_input",
        },
        {
            "from": "multisource_livability_scene",
            "to": "energy_regularized_planner_report",
            "relation": "energy_regularized_planner_graph_mdp_state_input",
        },
        {
            "from": "data_calibrated_mechanism_table",
            "to": "energy_regularized_planner_report",
            "relation": "energy_regularized_planner_mechanism_input",
        },
        {
            "from": "data_calibrated_spatial_spillover_kernel",
            "to": "energy_regularized_planner_report",
            "relation": "energy_regularized_planner_spatial_spillover_input",
        },
        {
            "from": "livability_graph_drl_training_report",
            "to": "energy_regularized_planner_report",
            "relation": "search_value_alignment_evidence_input",
        },
        {
            "from": "data_calibrated_planner_replay",
            "to": "endpoint_aligned_planner_evaluator",
            "relation": "planner_replay_endpoint_scoring_input",
        },
        {
            "from": "data_calibrated_planner_replay",
            "to": "spatial_spillover_planner_evaluator",
            "relation": "planner_replay_spillover_input",
        },
        {
            "from": "livability_endpoint_suite",
            "to": "livability_decision_package",
            "relation": "validated_endpoint_evidence_input",
        },
        {
            "from": "data_calibrated_planner_replay",
            "to": "livability_decision_package",
            "relation": "planner_replay_input",
        },
        {
            "from": "endpoint_aligned_planner_evaluator",
            "to": "livability_decision_package",
            "relation": "endpoint_advantage_evidence_input",
        },
        {
            "from": "spatial_spillover_planner_evaluator",
            "to": "livability_decision_package",
            "relation": "spatial_spillover_evidence_input",
        },
        {
            "from": "data_calibrated_spatial_spillover_kernel",
            "to": "livability_decision_package",
            "relation": "spatial_spillover_kernel_decision_evidence_input",
        },
        {
            "from": "livability_rl_training_report",
            "to": "livability_decision_package",
            "relation": "trained_model_based_rl_evidence_input",
        },
        {
            "from": "livability_graph_drl_training_report",
            "to": "livability_decision_package",
            "relation": "trained_graph_drl_evidence_input",
        },
        {
            "from": "livability_decision_package",
            "to": "traditional_vs_world_model_demo",
            "relation": "uwm_output_input",
        },
    ]


def _read_json_if_possible(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
