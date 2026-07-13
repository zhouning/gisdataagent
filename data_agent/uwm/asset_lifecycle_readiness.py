from __future__ import annotations

import hashlib
import json
from copy import deepcopy


LIFECYCLE_CHANNELS = (
    "authoritative_asset_id",
    "asset_type_taxonomy",
    "geometry_location",
    "owner_custodian_operator",
    "commissioning_acquisition_date",
    "lifecycle_status",
    "condition",
    "inspection",
    "maintenance_work_orders",
    "failures",
    "repair_replacement",
    "capacity_service_role",
    "valuation_cost_basis",
    "dependencies",
    "decommission_disposal",
    "successor_asset",
)

LIFECYCLE_MECHANISMS = (
    "entity_resolution",
    "asset_state_materialization",
    "degradation_modelling",
    "failure_transition_learning",
    "maintenance_response",
    "dependency_propagation",
    "replacement_planning",
    "recovery_modelling",
    "future_state_rollout",
)


def build_asset_lifecycle_readiness_product(*, source_products, source_artifacts):
    products = deepcopy(source_products)
    for product in products:
        if not product.get("source_path"):
            raise ValueError("asset_lifecycle_source_required")
        if product.get("asset_status") == "authoritative_assets" and not product.get("identity_evidence"):
            raise ValueError("authoritative_asset_claim_requires_identity_evidence")

    channels = {
        name: {
            "status": "unavailable",
            "value": None,
            "record_count": None,
            "production_blockers": ["authoritative_asset_identity_and_lifecycle_observations_missing"],
        }
        for name in LIFECYCLE_CHANNELS
    }
    contracts = {
        "asset_identity": {
            "required_fields": [
                "asset_id",
                "asset_type",
                "geometry_reference",
                "owner_or_custodian",
                "operator",
                "source_authority",
                "version",
                "provenance",
            ]
        },
        "asset_lifecycle_event": {
            "required_fields": [
                "event_id",
                "asset_id",
                "event_type",
                "event_time",
                "condition_before",
                "condition_after",
                "intervention",
                "cost",
                "dependency_context",
                "source_authority",
                "provenance",
            ]
        },
    }
    gate = {
        "status": "closed",
        "mechanisms": {name: "closed" for name in LIFECYCLE_MECHANISMS},
        "asset_identity_status": "closed",
        "lifecycle_observation_status": "closed",
        "uwm_lifecycle_kernel_status": "closed",
    }
    digest = {"source_products": products, "lifecycle_channels": channels}
    bundle_id = "asset-lifecycle-" + hashlib.sha256(
        json.dumps(digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]
    return {
        "schema": "uwm.asset_lifecycle_readiness.v1",
        "bundle_id": bundle_id,
        "summary": {
            "source_product_count": len(products),
            "source_record_count_total": None,
            "unique_asset_count": None,
            "available_lifecycle_channel_count": 0,
            "materialized_asset_state_count": 0,
            "observed_lifecycle_event_count": 0,
            "open_lifecycle_mechanism_count": 0,
        },
        "source_products": products,
        "lifecycle_channels": channels,
        "data_contracts": contracts,
        "lifecycle_gate": gate,
        "source_artifacts": sorted(map(str, source_artifacts)),
        "claim_boundary": {
            "max_claim_level": "cross_product_asset_catalog_lifecycle_contract_and_uwm_asset_state_readiness",
            "source_record_count_not_unique_asset_count": True,
            "poi_not_authoritative_asset": True,
            "building_footprint_not_ownership_or_condition": True,
            "facility_category_not_capacity": True,
            "cultural_candidate_not_registered_heritage_asset": True,
            "missing_maintenance_not_good_condition": True,
            "catalog_presence_not_lifecycle_observation": True,
            "lifecycle_contract_not_degradation_calibration": True,
        },
        "fabricated_value_count": 0,
    }
