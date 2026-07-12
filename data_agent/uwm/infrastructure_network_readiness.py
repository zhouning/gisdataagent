from __future__ import annotations

import hashlib
import json
from copy import deepcopy


CHANNELS = ("water_supply_network", "drainage_sewer_network", "electricity_network", "gas_network", "telecom_fibre_network", "district_energy_network", "utility_nodes_facilities", "network_topology", "capacity_design_rating", "ownership_operator", "observed_load_pressure_flow", "condition_maintenance", "outage_failure_events", "restoration_recovery", "cross_network_dependencies")


def build_infrastructure_network_readiness_product(*, assets, source_artifacts):
    rows = deepcopy(assets)
    for row in rows:
        if not row.get("source_path"): raise ValueError("infrastructure_source_required")
        if row.get("source_kind") == "commuting_od_proxy" and row.get("asset_role") == "telecom_network_observation": raise ValueError("commuting_proxy_not_telecom_network")
    channels = {name: {"status": "unavailable", "value": None, "record_count": None, "production_blockers": ["authoritative_utility_network_capacity_operations_data_missing"]} for name in CHANNELS}
    contracts = {"utility_network_observation": {"required_fields": ["asset_id", "network_type", "geometry_reference", "node_or_edge_role", "operator", "design_capacity", "capacity_unit", "observed_load", "observation_time", "condition", "failure_status", "dependency_edges", "source_authority", "version", "provenance"]}}
    mechanisms = ("infrastructure_state_materialization", "utility_topology_construction", "capacity_stress_estimation", "failure_propagation", "cross_network_cascade", "intervention_response", "repair_scheduling", "recovery_dynamics", "future_state_rollout")
    gate = {"status": "closed", "mechanisms": {name: "closed" for name in mechanisms}, "utility_observation_status": "closed", "uwm_cascade_kernel_status": "closed"}
    digest = {"assets": rows, "channels": channels}; bundle_id = "infrastructure-network-" + hashlib.sha256(json.dumps(digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return {"schema": "uwm.infrastructure_network_readiness.v1", "bundle_id": bundle_id, "summary": {"evidence_asset_count": len(rows), "visible_road_feature_count": sum(int(row.get("feature_count") or 0) for row in rows if row.get("asset_role") == "visible_road_inventory"), "visible_building_feature_count": sum(int(row.get("feature_count") or 0) for row in rows if row.get("asset_role") == "visible_building_inventory"), "available_utility_channel_count": 0, "materialized_utility_state_count": 0, "open_kernel_mechanism_count": 0}, "infrastructure_assets": rows, "utility_channels": channels, "data_contracts": contracts, "kernel_gate": gate, "source_artifacts": sorted(map(str, source_artifacts)), "claim_boundary": {"max_claim_level": "visible_infrastructure_inventory_utility_data_contract_and_cascade_kernel_readiness", "road_line_not_utility_pipe_or_cable": True, "building_footprint_not_asset_condition": True, "commuting_od_not_telecom_network": True, "field_standard_not_observed_infrastructure": True, "asset_count_not_service_capacity": True, "missing_outage_not_reliable_operation": True, "topology_availability_not_failure_propagation_calibration": True}, "fabricated_value_count": 0}
