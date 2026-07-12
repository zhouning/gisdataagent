from __future__ import annotations

import hashlib
import json
from copy import deepcopy

SCHEMA = "traditional_livability.housing_community_evidence.v1"
VIEWS = {
    "building_morphology_context": {"demand_id": "13"},
    "population_context": {"demand_id": "13"},
    "housing_evidence_readiness": {"demand_id": "13"},
}
CHANNELS = {
    "building_morphology": "implemented",
    "district_population": "implemented",
    "downscaled_population": "proxy_only",
    "service_neighbourhood_context": "proxy_only",
    "housing_type": "unavailable",
    "housing_unit_count": "unavailable",
    "residential_floor_area": "unavailable",
    "vacancy": "unavailable",
    "price_rent_affordability": "unavailable",
    "affordability": "unavailable",
    "tenure": "unavailable",
    "household_size_composition": "unavailable",
    "worker_accommodation": "unavailable",
    "family_suitability": "unavailable",
    "crowding": "unavailable",
    "housing_job_observed_proximity": "unavailable",
    "mixed_use_balance": "unavailable",
    "housing_demand_shortage": "unavailable",
    "development_recommendations": "unavailable",
    "causal_policy_effects": "unavailable",
}


def _empty_morphology():
    return {"join_status": "incompatible", "building_count": None, "floor_count_sum": None, "average_floor": None, "max_floor": None, "assignment_rule": None, "bbox_area_degrees2": None, "service_point_count": None, "essential_service_count": None, "ghsl_population_proxy_sum": None, "ghsl_built_surface_proxy_sum": None}


def _empty_proxy():
    return {"join_status": "incompatible", "admin_code": None, "district_resident_population": None, "downscaled_population": None, "allocation_weight": None, "allocation_basis": None, "synthetic_status": None}


def _empty_district():
    return {"join_status": "reference_only", "admin_code": None, "district_name": None, "year": None, "registered_households_10k": None, "registered_population_10k": None, "registered_urban_population_10k": None, "registered_rural_population_10k": None, "resident_population_10k": None, "resident_urban_population_10k": None, "urbanization_rate_percent": None}


def build_housing_community_product(*, morphology_rows, population_proxy_rows, district_rows, source_artifacts):
    morphology_by_id = {str(row["admin_unit_id"]): deepcopy(row) for row in morphology_rows if row.get("admin_unit_id")}
    proxy_by_id = {str(row["admin_unit_id"]): deepcopy(row) for row in population_proxy_rows if row.get("admin_unit_id")}
    district_by_code = {str(row["admin_code"]): deepcopy(row) for row in district_rows if row.get("admin_code")}
    admin_ids = sorted(set(morphology_by_id) | set(proxy_by_id))
    rows = []
    exact_morphology = exact_proxy = aggregate_district = 0
    for admin_id in admin_ids:
        morphology = morphology_by_id.get(admin_id)
        proxy = proxy_by_id.get(admin_id)
        county = (proxy or morphology or {}).get("county")
        township = (proxy or morphology or {}).get("township")
        morphology_context = _empty_morphology()
        if morphology:
            exact_morphology += 1
            morphology_context.update({key: morphology.get(key) for key in morphology_context if key != "join_status"})
            morphology_context["join_status"] = "exact_supported"
        proxy_context = _empty_proxy()
        if proxy:
            exact_proxy += 1
            proxy_context.update({key: proxy.get(key) for key in proxy_context if key != "join_status"})
            proxy_context["join_status"] = "exact_supported"
        district_context = _empty_district()
        admin_code = str(proxy.get("admin_code")) if proxy and proxy.get("admin_code") else None
        district = district_by_code.get(admin_code) if admin_code else None
        if district:
            aggregate_district += 1
            district_context.update({key: district.get(key) for key in district_context if key != "join_status"})
            district_context["join_status"] = "aggregate_supported"
        service_context = {
            "join_status": "exact_supported" if morphology else "incompatible",
            "service_point_count": morphology.get("service_point_count") if morphology else None,
            "essential_service_count": morphology.get("essential_service_count") if morphology else None,
            "interpretation": "source_morphology_neighbourhood_context_not_observed_housing_service_proximity",
        }
        missing = []
        if not morphology: missing.append("building_morphology_missing")
        if not proxy: missing.append("downscaled_population_proxy_missing")
        if not district: missing.append("district_population_context_missing")
        if not morphology or morphology.get("service_point_count") is None: missing.append("service_neighbourhood_context_missing")
        priorities = []
        if "building_morphology_missing" in missing: priorities.append("collect_or_align_building_morphology_by_exact_admin_unit_id")
        if "downscaled_population_proxy_missing" in missing: priorities.append("prepare_population_context_with_explicit_admin_unit_id")
        if "district_population_context_missing" in missing: priorities.append("document_parent_district_admin_code")
        priorities.extend(["collect_housing_unit_and_use_inventory", "collect_price_rent_and_tenure_observations", "collect_household_composition_microdata"])
        rows.append({
            "admin_unit_id": admin_id, "county": county, "township": township,
            "building_morphology_context": morphology_context,
            "population_proxy_context": proxy_context,
            "district_population_context": district_context,
            "service_neighbourhood_context": service_context,
            "evidence_coverage": {"supported_channel_count": 4 - len(missing), "missing_channel_count": len(missing)},
            "evidence_gap_reasons": missing, "field_collection_priorities": priorities,
            "source_trace": {"morphology_admin_unit_id": admin_id if morphology else None, "population_proxy_admin_unit_id": admin_id if proxy else None, "district_admin_code": admin_code if district else None},
            "limitations": {"building_count_not_housing_unit_count": True, "floor_count_not_residential_floor_area": True, "building_morphology_not_housing_type": True, "building_assignment_not_cadastral_inventory": True, "downscaled_population_not_census_microdata": True, "allocation_weight_not_observed_household_distribution": True, "population_proxy_not_observed_household_count": True, "population_density_not_housing_crowding": True, "population_proxy_not_service_demand_observation": True, "relative_gap_not_authoritative_housing_shortage": True},
        })
    ordered = sorted(rows, key=lambda row: (-row["evidence_coverage"]["missing_channel_count"], row["evidence_coverage"]["supported_channel_count"], row["admin_unit_id"]))
    for rank, row in enumerate(ordered, 1): row["relative_housing_community_evidence_gap_rank"] = rank
    digest = {"admins": rows, "sources": sorted(map(str, source_artifacts))}
    bundle_id = "traditional-housing-community-" + hashlib.sha256(json.dumps(digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return {
        "schema": SCHEMA, "bundle_id": bundle_id, "views": deepcopy(VIEWS),
        "summary": {"admin_unit_count": len(rows), "morphology_source_row_count": len(morphology_rows), "population_proxy_source_row_count": len(population_proxy_rows), "district_population_source_row_count": len(district_rows), "exact_morphology_match_count": exact_morphology, "exact_population_proxy_match_count": exact_proxy, "aggregate_district_match_count": aggregate_district},
        "admin_units": sorted(rows, key=lambda row: row["admin_unit_id"]),
        "channel_readiness": {name: {"status": status, "value": None if status == "unavailable" else status} for name, status in CHANNELS.items()},
        "evidence_sources": [{"path": str(path), "role": role} for path, role in zip(source_artifacts, ["building_morphology", "district_population", "downscaled_population"])],
        "claim_boundary": {"max_claim_level": "building_morphology_population_context_and_housing_evidence_readiness", "housing_stock_claim": False, "affordability_claim": False, "household_composition_claim": False, "housing_shortage_claim": False, "causal_policy_effect_claim": False},
        "fabricated_value_count": 0,
        "production_blockers": ["housing_unit_inventory_missing", "residential_use_and_floor_area_missing", "price_rent_affordability_missing", "tenure_missing", "household_composition_microdata_missing", "housing_job_observed_proximity_missing", "causal_housing_transition_model_missing"],
    }
