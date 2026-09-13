from copy import deepcopy

import pytest

from data_agent.test_traditional_livability_s7 import _inputs
from data_agent.uwm.traditional_livability_s7_gated import run_gated_s7


def _gate(state, required_site_count=None):
    return {
        "schema": "uwm.traditional_livability.s7_demand_gate.v1",
        "gate_id": f"gate-{state}",
        "state": state,
        "standard_class_id": "education.primary_school",
        "required_site_count": required_site_count,
        "gap": {"gap_type": "facility_count_gap", "gap_value": required_site_count, "unit": "count"},
        "gap_closure_assessed": required_site_count is not None,
        "blockers": ["authoritative_s1_metric_profile_missing"] if state == "need_unresolved" else [],
    }


def _run(gate, **kwargs):
    params = {
        "mode": "authoritative",
        "acknowledgement": False,
        "gate": gate,
        "siting_id": "s7-gated",
        "created_at": "2026-07-11T12:00:00+08:00",
        "planning_inputs": _inputs(),
        "school_supply": [],
        "coverage_distance_m": 600,
        "requested_max_sites": 5,
    }
    params.update(kwargs)
    return run_gated_s7(**params)


def test_unresolved_need_allows_only_acknowledged_conditional_ranking():
    with pytest.raises(ValueError, match="conditional_not_a_recommendation_ack_required"):
        _run(_gate("need_unresolved"), mode="conditional")
    result = _run(_gate("need_unresolved"), mode="conditional", acknowledgement=True)
    assert result["recommendation_status"] == "conditional_candidate_ranking_available"
    assert result["not_a_site_recommendation"] is True
    assert all(row["not_a_site_recommendation"] for row in result["ranked_candidates"])
    assert all(row["not_a_site_recommendation"] for row in result["selected_sites"])
    assert result["claim_boundary"]["max_claim_level"] == "conditional_static_candidate_ranking"


def test_positive_count_gap_caps_selected_sites_and_allows_authoritative_wording():
    result = _run(_gate("authoritative_need_confirmed", required_site_count=1))
    assert result["recommendation_status"] == "authoritative_site_recommendation_available"
    assert len(result["selected_sites"]) == 1
    assert result["selected_sites"][0]["site_role"] == "primary"
    assert result["not_a_site_recommendation"] is False


def test_authoritative_no_need_returns_no_siting_without_running_ranking():
    result = _run(_gate("authoritative_need_not_confirmed", required_site_count=0))
    assert result["recommendation_status"] == "no_siting_required"
    assert result["ranked_candidates"] == []
    assert result["selected_sites"] == []


def test_authoritative_mode_rejects_unresolved_gate():
    with pytest.raises(ValueError, match="authoritative_need_not_confirmed"):
        _run(_gate("need_unresolved"))


def test_conditional_mode_preserves_legacy_candidate_order_and_inputs():
    planning = _inputs()
    before = deepcopy(planning)
    result = _run(
        _gate("need_unresolved"), mode="conditional", acknowledgement=True, planning_inputs=planning
    )
    assert [row["parcel_id"] for row in result["selected_sites"]] == ["candidate-best", "candidate-second"]
    assert planning == before


def test_area_or_capacity_gap_does_not_claim_closure_without_proposal_attributes():
    gate = _gate("authoritative_need_confirmed")
    gate["gap"] = {"gap_type": "facility_capacity_gap", "gap_value": 100, "unit": "capacity"}
    gate["gap_closure_assessed"] = False
    result = _run(gate, requested_max_sites=2)
    assert result["gap_closure_assessed"] is False
    assert result["remaining_gap"] is None
