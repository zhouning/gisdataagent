from __future__ import annotations

import math
from typing import Any


SCHEMA = "uwm.traditional_livability.s7_siting.v1"
DISTANCE_PROVIDER = "projected_straight_line_distance_proxy"


def build_s7_primary_school_siting(
    *,
    siting_id: str,
    created_at: str,
    planning_inputs: dict[str, Any],
    school_supply: list[dict[str, Any]],
    coverage_distance_m: float,
    max_sites: int,
) -> dict[str, Any]:
    if coverage_distance_m <= 0:
        raise ValueError("coverage_distance_m_must_be_positive")
    if max_sites <= 0:
        raise ValueError("max_sites_must_be_positive")

    demands = list(planning_inputs.get("demand_parcels") or [])
    candidates = list(planning_inputs.get("candidate_parcels") or [])
    excluded = list(planning_inputs.get("excluded_parcels") or [])
    local_supply = [
        row
        for row in school_supply
        if row.get("supply_verification_status") == "locally_verified_current_supply"
    ]
    baseline_ids = {
        _demand_id(demand)
        for demand in demands
        if any(_within(demand, supply, coverage_distance_m) for supply in local_supply)
    }
    total_area = sum(_weight(row) for row in demands)
    baseline_area = _area_for_ids(demands, baseline_ids)
    funnel = _filter_funnel(candidates, excluded)
    blockers = _blockers(planning_inputs, candidates)
    if not candidates:
        return {
            **_base_payload(siting_id, created_at, planning_inputs, coverage_distance_m, max_sites),
            "recommendation_status": "no_recommendation",
            "candidate_filter_funnel": funnel,
            "demand_summary": _demand_summary(total_area, baseline_area, baseline_area, len(demands)),
            "ranked_candidates": [],
            "selected_sites": [],
            "geometry_payload": _geometry_payload([], demands, [], excluded, coverage_distance_m),
            "production_blockers": blockers,
            "claim_boundary": _claim_boundary(),
        }

    covered_ids = set(baseline_ids)
    ranked_all: dict[str, dict[str, Any]] = {}
    selected: list[dict[str, Any]] = []
    remaining = list(candidates)
    for round_index in range(1, max_sites + 1):
        round_rows = [_score_candidate(candidate, demands, covered_ids, coverage_distance_m) for candidate in remaining]
        round_rows.sort(key=_rank_key)
        for row in round_rows:
            ranked_all[row["candidate_key"]] = {**row, "selection_round": None}
        if not round_rows or round_rows[0]["newly_covered_proxy_area_m2"] <= 0:
            break
        winner = round_rows[0]
        winner["selection_round"] = round_index
        ranked_all[winner["candidate_key"]] = winner
        selected.append(winner)
        covered_ids.update(winner["covered_demand_ids"])
        remaining = [row for row in remaining if _candidate_key(row) != winner["candidate_key"]]

    ranked = sorted(
        ranked_all.values(),
        key=lambda row: (row["selection_round"] is None, row["selection_round"] or 999999, _rank_key(row)),
    )
    covered_area = _area_for_ids(demands, covered_ids)
    return {
        **_base_payload(siting_id, created_at, planning_inputs, coverage_distance_m, max_sites),
        "recommendation_status": "ranked_candidates_available" if selected else "no_positive_coverage_gain",
        "candidate_filter_funnel": funnel,
        "demand_summary": _demand_summary(total_area, baseline_area, covered_area, len(demands)),
        "ranked_candidates": ranked,
        "selected_sites": selected,
        "geometry_payload": _geometry_payload(selected, demands, candidates, excluded, coverage_distance_m),
        "production_blockers": blockers,
        "claim_boundary": _claim_boundary(),
    }


def _base_payload(siting_id, created_at, planning_inputs, coverage_distance_m, max_sites):
    manifest = planning_inputs.get("manifest") or {}
    return {
        "schema": SCHEMA,
        "siting_id": siting_id,
        "created_at": created_at,
        "executed_geography": "福禄镇和平村与斑竹村规划样例",
        "planning_area_ids": [row.get("planning_area_id") for row in planning_inputs.get("planning_areas") or []],
        "assumptions": {
            "facility_type": "education.primary_school",
            "demand_proxy": "residential_land_area_m2",
            "distance_cost_provider": DISTANCE_PROVIDER,
            "coverage_distance_m": coverage_distance_m,
            "max_sites": max_sites,
            "algorithm": "greedy_location_allocation",
            "tie_break_order": ["new_coverage_desc", "repeated_coverage_asc", "suitability_desc", "candidate_area_desc", "parcel_id_asc"],
        },
        "data_support": {
            "planning_scope": "fulu_heping_and_banzhu_planning_samples_only",
            "source_ready": bool(manifest.get("ready")),
            "source_manifest_schema": manifest.get("schema"),
            "source_manifest_reference_count": len(manifest.get("sources") or []),
        },
    }


def _score_candidate(candidate, demands, covered_ids, threshold):
    coverage = [demand for demand in demands if _within(demand, candidate, threshold)]
    ids = [_demand_id(row) for row in coverage]
    new_ids = [value for value in ids if value not in covered_ids]
    repeated_ids = [value for value in ids if value in covered_ids]
    return {
        "parcel_id": str(candidate.get("source_parcel_id")),
        "candidate_key": _candidate_key(candidate),
        "planning_area_id": candidate.get("planning_area_id"),
        "land_use_code": candidate.get("land_use_code"),
        "land_use_name": candidate.get("land_use_name"),
        "suitability_score": _float(candidate.get("suitability_score")),
        "candidate_area_m2": _float(candidate.get("area_m2")),
        "newly_covered_proxy_area_m2": _area_for_ids(demands, set(new_ids)),
        "repeated_coverage_proxy_area_m2": _area_for_ids(demands, set(repeated_ids)),
        "covered_demand_count": len(ids),
        "covered_demand_ids": ids,
        "display_centroid": candidate.get("display_centroid"),
        "distance_proxy_circle_radius_m": threshold,
    }


def _rank_key(row):
    return (
        -_float(row.get("newly_covered_proxy_area_m2")),
        _float(row.get("repeated_coverage_proxy_area_m2")),
        -_float(row.get("suitability_score")),
        -_float(row.get("candidate_area_m2")),
        str(row.get("candidate_key")),
    )


def _within(demand, target, threshold):
    if demand.get("planning_area_id") != target.get("planning_area_id"):
        return False
    demand_crs = demand.get("distance_crs")
    target_crs = target.get("distance_crs")
    if demand_crs and target_crs and demand_crs != target_crs:
        return False
    first, second = demand.get("projected_centroid") or {}, target.get("projected_centroid") or {}
    if not {"x", "y"} <= set(first) or not {"x", "y"} <= set(second):
        return False
    return math.hypot(float(first["x"]) - float(second["x"]), float(first["y"]) - float(second["y"])) <= threshold


def _filter_funnel(candidates, excluded):
    reason_counts: dict[str, int] = {}
    for row in excluded:
        reason = str(row.get("exclusion_reason") or "other_land_use")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {"eligible_candidate_count": len(candidates), "excluded_candidate_count": len(excluded), "excluded_by_reason": dict(sorted(reason_counts.items()))}


def _demand_summary(total, baseline, covered, count):
    return {"demand_parcel_count": count, "total_proxy_area_m2": total, "baseline_covered_proxy_area_m2": baseline, "covered_proxy_area_m2": covered, "unserved_proxy_area_m2": max(0.0, total - covered)}


def _geometry_payload(selected, demands, candidates, excluded, threshold):
    return {
        "selected_candidate_centroids": [{"parcel_id": row["parcel_id"], "planning_area_id": row["planning_area_id"], "centroid": row.get("display_centroid"), "distance_proxy_circle_radius_m": threshold} for row in selected],
        "demand_centroids": [{"parcel_id": _demand_id(row), "planning_area_id": row.get("planning_area_id"), "centroid": row.get("display_centroid"), "proxy_area_m2": _weight(row)} for row in demands],
        "candidate_centroids": [{"parcel_id": str(row.get("source_parcel_id")), "planning_area_id": row.get("planning_area_id"), "centroid": row.get("display_centroid")} for row in candidates],
        "excluded_candidates": [{"parcel_id": str(row.get("source_parcel_id")), "planning_area_id": row.get("planning_area_id"), "exclusion_reason": row.get("exclusion_reason")} for row in excluded],
    }


def _blockers(planning_inputs, candidates):
    blockers = [
        "authoritative_43_class_facility_dictionary_missing",
        "authoritative_fp_fpp_thresholds_missing",
        "school_capacity_enrolment_and_operating_status_missing",
        "student_and_school_age_population_missing",
        "complete_village_pedestrian_network_missing",
        "authoritative_parcel_ownership_acquisition_dcr_boq_and_finance_inputs_missing",
        "planning_data_limited_to_two_village_samples",
    ]
    if not candidates:
        blockers.append("candidate_policy_no_eligible_parcels")
    if not (planning_inputs.get("manifest") or {}).get("ready"):
        blockers.append("planning_inputs_not_ready")
    return blockers


def _claim_boundary():
    return {
        "walking_or_network_service_area_assessed": False,
        "school_capacity_or_compliance_assessed": False,
        "future_policy_benefit_predicted": False,
        "uwm_superiority_claimed": False,
        "selected_parcel_is_approved_school_site": False,
    }


def _demand_id(row):
    return f"{row.get('planning_area_id')}:{row.get('source_parcel_id')}"


def _candidate_key(row):
    return f"{row.get('planning_area_id')}:{row.get('source_parcel_id')}"


def _area_for_ids(rows, ids):
    return round(sum(_weight(row) for row in rows if _demand_id(row) in ids), 6)


def _weight(row):
    return _float(row.get("weight_m2"))


def _float(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
