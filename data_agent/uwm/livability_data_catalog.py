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
        "asset_id": "data_calibrated_planner_replay",
        "role": "planner_graph_search_replay",
        "path": "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json",
        "stage": "planner",
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
    core_ready = all(asset["exists"] for asset in core_assets)
    mmfe_count = len(mmfe_state_assets)
    local_count = sum(1 for asset in assets if asset["exists"])
    if graph_drl_training_completed:
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
            "policy_or_value_network_trained": False,
            "graph_policy_or_value_network_trained": graph_drl_training_completed,
            "current_planning_mode": current_planning_mode,
            "allowed_claim": allowed_claim,
        },
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
            asset["real_data_available_action_count"] = _int(
                training.get("real_data_available_action_count")
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
