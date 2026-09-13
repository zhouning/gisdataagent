from __future__ import annotations

import hashlib
import json
from copy import deepcopy


CHANNELS = ("source_geometry", "stable_feature_identifier", "current_land_use_code", "current_land_use_name", "planned_land_use_code", "planned_land_use_name", "observed_area", "administrative_join", "ownership_context", "development_approval_status", "current_planned_relation", "baseline_observation_version", "successor_observed_state", "transition_label", "action_intervention_linkage")


def build_parcel_state_readiness_product(*, source_assets, source_artifacts):
    assets = deepcopy(source_assets)
    for asset in assets:
        if not asset.get("source_path"): raise ValueError("parcel_state_source_required")
        if asset.get("version_status") != "verified" and asset.get("state_status") == "observed_t0": raise ValueError("unresolved_version_cannot_be_observed_state")
    channels = {name: {"status": "unavailable", "value": None, "record_count": None, "production_blockers": ["authoritative_feature_rows_and_version_baseline_missing"]} for name in CHANNELS}
    contracts = {"uwm_parcel_state": {"required_fields": ["state_node_id", "source_feature_id", "geometry_reference", "current_state_code", "state_taxonomy_version", "observation_time", "source_version_bundle", "quality_flags", "action_eligibility", "successor_observation", "provenance"]}}
    mechanisms = ("current_state_materialization", "land_use_code_domain_validation", "area_aggregation", "current_planned_overlay", "legal_status_classification", "conflict_screening", "uwm_t0_state_initialization", "transition_label_construction", "action_conditioned_transition_learning", "future_state_rollout")
    gate = {"status": "closed", "mechanisms": {name: "closed" for name in mechanisms}, "traditional_gis_state_status": "closed", "uwm_transition_status": "closed"}
    digest = {"assets": assets, "channels": channels}; bundle_id = "parcel-state-" + hashlib.sha256(json.dumps(digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return {"schema": "uwm.parcel_land_use_state_readiness.v1", "bundle_id": bundle_id, "summary": {"source_asset_count": len(assets), "audited_feature_count": sum(int(asset.get("feature_count") or 0) for asset in assets), "available_state_channel_count": 0, "materialized_state_node_count": 0, "observed_transition_count": 0, "open_state_mechanism_count": 0}, "source_assets": assets, "state_channels": channels, "data_contracts": contracts, "state_gate": gate, "source_artifacts": sorted(map(str, source_artifacts)), "claim_boundary": {"max_claim_level": "parcel_land_use_schema_audit_state_contract_and_uwm_transition_readiness", "audited_feature_count_not_current_land_use_distribution": True, "dltb_identifier_not_legal_parcel_title": True, "land_use_class_not_development_permission": True, "profile_metadata_not_observed_parcel_state": True, "missing_planned_use_not_no_conflict": True, "missing_successor_not_persistence": True, "schema_readiness_not_transition_calibration": True}, "fabricated_value_count": 0}
