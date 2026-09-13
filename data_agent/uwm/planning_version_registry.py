from __future__ import annotations

import hashlib
import json
from copy import deepcopy


CHANNELS = ("approval_identifier", "version_identifier", "effective_start", "effective_end", "spatial_applicability", "predecessor_version", "successor_version", "change_reason", "immutable_source_hash", "authoritative_current_version")


def build_planning_version_registry(*, assets, source_artifacts):
    rows = deepcopy(assets)
    for row in rows:
        if not row.get("source_path"): raise ValueError("planning_asset_source_required")
        if row.get("approval_status") != "verified" and row.get("version_status") == "current": raise ValueError("unverified_asset_cannot_be_current")
    channels = {name: {"status": "unavailable", "value": None, "production_blockers": ["authoritative_version_lineage_missing"]} for name in CHANNELS}
    contracts = {"authoritative_planning_version": {"required_fields": ["source_authority", "approval_or_publication_identifier", "version_identifier", "effective_start", "effective_end", "spatial_applicability", "object_type", "crs", "schema_reference", "immutable_source_hash", "predecessor_version", "successor_version", "change_reason", "citation"]}}
    mechanisms = ("authoritative_baseline_selection", "current_version_resolution", "predecessor_successor_traversal", "parcel_history_reconstruction", "plan_amendment_comparison", "temporal_outcome_join", "uwm_state_initialization_from_approved_plan", "uwm_transition_attribution_to_planning_change")
    gate = {"status": "closed", "mechanisms": {name: "closed" for name in mechanisms}, "uwm_temporal_baseline_status": "closed"}
    digest = {"assets": rows, "channels": channels}; bundle_id = "planning-version-" + hashlib.sha256(json.dumps(digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return {"schema": "uwm.planning_parcel_version_registry.v1", "bundle_id": bundle_id, "summary": {"version_asset_count": len(rows), "verified_approval_asset_count": sum(row.get("approval_status") == "verified" for row in rows), "authoritative_current_version_count": 0, "available_version_channel_count": 0, "open_temporal_mechanism_count": 0}, "version_assets": rows, "version_channels": channels, "data_contracts": contracts, "temporal_gate": gate, "source_artifacts": sorted(map(str, source_artifacts)), "claim_boundary": {"max_claim_level": "planning_parcel_asset_inventory_version_contract_and_temporal_baseline_readiness", "audit_creation_time_not_plan_effective_date": True, "folder_year_not_authoritative_version": True, "sample_demo_asset_not_approved_planning_database": True, "dltb_feature_not_legal_parcel_title": True, "ledger_row_not_spatial_parcel_history": True, "asset_inventory_not_version_lineage": True, "missing_successor_not_current_status": True}, "fabricated_value_count": 0}
