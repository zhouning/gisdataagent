from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from data_agent.uwm.traditional_livability_s7 import build_s7_primary_school_siting


SCHEMA = "uwm.traditional_livability.s7_gated_siting.v1"


def _no_siting_payload(gate, *, siting_id, created_at):
    return {
        "schema": SCHEMA,
        "siting_id": siting_id,
        "created_at": created_at,
        "mode": "authoritative",
        "recommendation_status": "no_siting_required",
        "demand_gate": deepcopy(gate),
        "ranked_candidates": [],
        "selected_sites": [],
        "not_a_site_recommendation": False,
        "gap_closure_assessed": True,
        "remaining_gap": 0,
        "production_blockers": [],
        "claim_boundary": {
            "max_claim_level": "authoritative_no_siting_need",
            "uwm_rollout": False,
            "future_demand_modelled": False,
        },
    }


def run_gated_s7(
    *,
    mode: str,
    acknowledgement: bool,
    gate: Mapping[str, Any],
    siting_id: str,
    created_at: str,
    planning_inputs: Mapping[str, Any],
    school_supply: list[Mapping[str, Any]],
    coverage_distance_m: float,
    requested_max_sites: int,
) -> dict[str, Any]:
    gate_copy = deepcopy(dict(gate))
    state = gate_copy.get("state")
    if state == "authoritative_need_not_confirmed":
        return _no_siting_payload(gate_copy, siting_id=siting_id, created_at=created_at)
    if mode == "authoritative":
        if state != "authoritative_need_confirmed":
            raise ValueError("authoritative_need_not_confirmed")
        required = gate_copy.get("required_site_count")
        max_sites = min(requested_max_sites, required) if isinstance(required, int) and required > 0 else requested_max_sites
        conditional = False
    elif mode == "conditional":
        if state != "need_unresolved":
            raise ValueError("conditional_mode_requires_unresolved_need")
        if acknowledgement is not True:
            raise ValueError("conditional_not_a_recommendation_ack_required")
        max_sites = requested_max_sites
        conditional = True
    else:
        raise ValueError("unsupported_s7_run_mode")
    base = build_s7_primary_school_siting(
        siting_id=siting_id,
        created_at=created_at,
        planning_inputs=deepcopy(dict(planning_inputs)),
        school_supply=deepcopy(list(school_supply)),
        coverage_distance_m=coverage_distance_m,
        max_sites=max_sites,
    )
    ranked = deepcopy(base.get("ranked_candidates") or [])
    selected = deepcopy(base.get("selected_sites") or [])
    if conditional:
        ranked = [{**row, "not_a_site_recommendation": True} for row in ranked]
        selected = [{**row, "not_a_site_recommendation": True} for row in selected]
        status = "conditional_candidate_ranking_available" if ranked else "conditional_ranking_unavailable"
        max_claim = "conditional_static_candidate_ranking"
    else:
        ranked = [{**row, "not_a_site_recommendation": False} for row in ranked]
        selected = [
            {
                **row,
                "not_a_site_recommendation": False,
                "site_role": "primary" if index == 0 else "backup",
            }
            for index, row in enumerate(selected)
        ]
        status = "authoritative_site_recommendation_available" if selected else "authoritative_no_positive_coverage_gain"
        max_claim = "authoritative_need_gated_static_siting"
    gap_closure_assessed = bool(gate_copy.get("gap_closure_assessed"))
    remaining_gap = None
    if gap_closure_assessed and gate_copy.get("gap", {}).get("gap_type") == "facility_count_gap":
        value = gate_copy.get("gap", {}).get("gap_value")
        if isinstance(value, (int, float)):
            remaining_gap = max(0.0, round(float(value) - len(selected), 6))
    return deepcopy({
        **base,
        "schema": SCHEMA,
        "mode": mode,
        "recommendation_status": status,
        "demand_gate": gate_copy,
        "ranked_candidates": ranked,
        "selected_sites": selected,
        "not_a_site_recommendation": conditional,
        "gap_closure_assessed": gap_closure_assessed,
        "remaining_gap": remaining_gap,
        "production_blockers": list(dict.fromkeys([*(base.get("production_blockers") or []), *(gate_copy.get("blockers") or [])])),
        "claim_boundary": {
            **deepcopy(base.get("claim_boundary") or {}),
            "max_claim_level": max_claim,
            "uwm_rollout": False,
            "future_demand_modelled": False,
        },
    })
