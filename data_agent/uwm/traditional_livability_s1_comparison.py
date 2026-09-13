from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from data_agent.uwm.traditional_livability_s1_fp import evaluate_fp
from data_agent.uwm.traditional_livability_s1_fpp import evaluate_fpp
from data_agent.uwm.traditional_livability_s1_synthesis import synthesize_s1_dimensions


SCHEMA = "uwm.traditional_livability.s1_static_comparison.v1"


def _unresolved(blockers):
    return {
        "schema": SCHEMA,
        "status": "unresolved",
        "method": "deterministic_static_proposal_comparison",
        "blockers": list(dict.fromkeys(blockers)),
        "claim_boundary": {
            "uwm_rollout": False,
            "future_adaptation_assessed": False,
            "policy_outcome_predicted": False,
        },
    }


def _proposed_facility(handoff: Mapping[str, Any]) -> dict[str, Any]:
    proposal = handoff.get("proposal")
    proposal = proposal if isinstance(proposal, Mapping) else {}
    class_id = handoff.get("confirmed_standard_class_id")
    return {
        "facility_id": f"proposal:{handoff.get('handoff_id')}",
        "facility_name": proposal.get("facility_name"),
        "canonical_class": class_id,
        "admin_code": proposal.get("analysis_area_id"),
        "metric_geometry": deepcopy(proposal.get("metric_geometry")),
        "metric_crs": proposal.get("metric_crs"),
        "display_geometry": deepcopy(proposal.get("proposed_geometry")),
        "facility_area_m2": proposal.get("facility_area_m2"),
        "capacity": proposal.get("capacity"),
        "record_status": "proposed_static_snapshot",
        "source_handoff_id": handoff.get("handoff_id"),
    }


def _evaluate_snapshot(
    *, facilities, population_units, demand_units, profile, synthesis_matrix, admin_code, complete_inventory
):
    dimensions = profile.get("dimensions") or []
    fp = None
    fpp = None
    if "FP" in dimensions:
        fp = evaluate_fp(
            facilities=facilities,
            demand_units=demand_units,
            profile=profile,
            admin_code=admin_code,
            complete_facility_inventory=complete_inventory,
        )
    if "FPP" in dimensions:
        fpp = evaluate_fpp(
            facilities=facilities,
            population_units=population_units,
            profile=profile,
            admin_code=admin_code,
            complete_facility_inventory=complete_inventory,
        )
    if fp is not None and fpp is not None:
        synthesis = synthesize_s1_dimensions(fp=fp, fpp=fpp, matrix=synthesis_matrix)
    else:
        only = fp if fp is not None else fpp
        synthesis = {
            "status": only.get("status") if only else "unresolved",
            "blockers": deepcopy(only.get("blockers") if only else ["s1_dimension_missing"]),
            "max_claim_level": only.get("max_claim_level") if only else "unresolved",
        }
    return {
        "facility_ids": [row.get("facility_id") for row in facilities],
        "fp": fp,
        "fpp": fpp,
        "synthesis": synthesis,
    }


def _delta(baseline, proposal):
    if not isinstance(baseline, Mapping) or not isinstance(proposal, Mapping):
        return None
    left = baseline.get("observed_value")
    right = proposal.get("observed_value")
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return None
    return round(float(right) - float(left), 6)


def compare_s1_baseline_and_proposal(
    *,
    handoff: Mapping[str, Any],
    facility_product: Mapping[str, Any],
    demand_units: list[Mapping[str, Any]],
    profile: Mapping[str, Any],
    synthesis_matrix: Mapping[str, Any],
) -> dict[str, Any]:
    handoff_copy = deepcopy(dict(handoff))
    product = deepcopy(dict(facility_product))
    profile_copy = deepcopy(dict(profile))
    matrix_copy = deepcopy(dict(synthesis_matrix))
    blockers = []
    if handoff_copy.get("ready_for_s1") is not True:
        blockers.append("handoff_not_ready_for_s1")
    source_bundle = handoff_copy.get("source_resource_bundle")
    source_bundle = source_bundle if isinstance(source_bundle, Mapping) else {}
    if source_bundle.get("bundle_id") != product.get("bundle_id"):
        blockers.append("facility_product_bundle_mismatch")
    supplied_profile_bundle = profile_copy.get("profile_bundle_id")
    if supplied_profile_bundle is not None and supplied_profile_bundle != handoff_copy.get("metric_profile_bundle_id"):
        blockers.append("metric_profile_bundle_mismatch")
    if profile_copy.get("standard_class_id") != handoff_copy.get("confirmed_standard_class_id"):
        blockers.append("metric_profile_class_mismatch")
    proposal = handoff_copy.get("proposal")
    proposal = proposal if isinstance(proposal, Mapping) else {}
    admin_code = proposal.get("analysis_area_id")
    if not admin_code:
        blockers.append("analysis_area_required")
    if blockers:
        return _unresolved(blockers)

    baseline_facilities = deepcopy(product.get("facilities") or [])
    proposal_facilities = deepcopy(baseline_facilities)
    proposed = _proposed_facility(handoff_copy)
    proposal_facilities.append(proposed)
    population_units = deepcopy(product.get("population_units") or [])
    complete_inventory = bool((product.get("source_manifest") or {}).get("complete_inventory"))
    baseline = _evaluate_snapshot(
        facilities=baseline_facilities,
        population_units=population_units,
        demand_units=deepcopy(demand_units),
        profile=profile_copy,
        synthesis_matrix=matrix_copy,
        admin_code=admin_code,
        complete_inventory=complete_inventory,
    )
    proposal_snapshot = _evaluate_snapshot(
        facilities=proposal_facilities,
        population_units=population_units,
        demand_units=deepcopy(demand_units),
        profile=profile_copy,
        synthesis_matrix=matrix_copy,
        admin_code=admin_code,
        complete_inventory=complete_inventory,
    )
    if "FP" in (profile_copy.get("dimensions") or []) and proposed.get("metric_geometry") is None:
        proposal_snapshot["fp"] = {
            "schema": "uwm.traditional_livability.s1_fp_assessment.v1",
            "dimension": "FP",
            "status": "unresolved",
            "observed_value": None,
            "blockers": ["proposal_metric_geometry_missing"],
            "max_claim_level": "unresolved",
            "geojson": {},
        }
        if proposal_snapshot.get("fpp") is not None:
            proposal_snapshot["synthesis"] = synthesize_s1_dimensions(
                fp=proposal_snapshot["fp"], fpp=proposal_snapshot["fpp"], matrix=matrix_copy
            )

    comparison = {
        "fp_delta": _delta(baseline.get("fp"), proposal_snapshot.get("fp")),
        "fpp_delta": _delta(baseline.get("fpp"), proposal_snapshot.get("fpp")),
        "baseline_combined_status": baseline["synthesis"].get("status"),
        "proposal_combined_status": proposal_snapshot["synthesis"].get("status"),
    }
    return deepcopy(
        {
            "schema": SCHEMA,
            "status": "completed",
            "method": "deterministic_static_proposal_comparison",
            "handoff_id": handoff_copy.get("handoff_id"),
            "facility_product_id": product.get("product_id"),
            "profile_id": profile_copy.get("profile_id"),
            "baseline": baseline,
            "proposal_snapshot": proposal_snapshot,
            "comparison": comparison,
            "blockers": [],
            "claim_boundary": {
                "uwm_rollout": False,
                "future_adaptation_assessed": False,
                "policy_outcome_predicted": False,
                "max_claim_level": "deterministic_static_proposal_comparison",
            },
        }
    )
