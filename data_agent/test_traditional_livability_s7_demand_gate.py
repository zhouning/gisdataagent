from copy import deepcopy

from data_agent.uwm.traditional_livability_s7_demand_gate import build_s7_demand_gate


def _crosswalk(status="valid"):
    return {
        "status": status,
        "crosswalk_id": "bishan-fulu-v1",
        "content_digest": "sha256:crosswalk",
        "s1_geography_id": "500120",
        "requested_s7_area_ids": ["fulu_heping", "fulu_banzhu"],
        "matched_rows": [{"s7_planning_area_id": "fulu_heping"}, {"s7_planning_area_id": "fulu_banzhu"}],
        "blockers": [] if status == "valid" else ["crosswalk_invalid"],
    }


def _assessment(*, status="does_not_meet", gap_value=2.2, gap_type="facility_count_gap"):
    return {
        "assessment_id": "s1-primary-school-v1",
        "content_digest": "sha256:s1",
        "created_at": "2026-07-11T10:00:00+08:00",
        "standard_class_id": "education.primary_school",
        "admin_code": "500120",
        "facility_product_id": "facility-v1",
        "facility_bundle_id": "facility-bundle-v1",
        "facility_snapshot_at": "2026-07-11T09:00:00+08:00",
        "profile": {
            "status": "valid",
            "authority_level": "authoritative",
            "profile_id": "primary-school-fpp-v1",
            "content_digest": "sha256:profile",
        },
        "synthesis_matrix": None,
        "applicable_result": {
            "status": status,
            "gap_type": gap_type,
            "gap_value": gap_value,
            "unit": "count" if gap_type == "facility_count_gap" else "capacity",
            "observed_value": 1.0,
            "threshold": 3.2,
            "comparator": ">=",
        },
        "complete_inventory": True,
        "uncertainty": "low",
    }


def _s7_product():
    return {
        "product_id": "s7-fulu-v1",
        "bundle_id": "facility-bundle-v1",
        "snapshot_at": "2026-07-11T09:00:00+08:00",
        "facility_class_id": "education.primary_school",
        "planning_area_ids": ["fulu_heping", "fulu_banzhu"],
        "content_digest": "sha256:s7",
    }


def _build(**overrides):
    params = {
        "s1_assessment": _assessment(),
        "s7_product": _s7_product(),
        "crosswalk_validation": _crosswalk(),
        "created_at": "2026-07-11T11:00:00+08:00",
    }
    params.update(overrides)
    return build_s7_demand_gate(**params)


def test_positive_authoritative_count_gap_confirms_need():
    gate = _build()
    assert gate["state"] == "authoritative_need_confirmed"
    assert gate["required_site_count"] == 3
    assert gate["gap"]["gap_value"] == 2.2


def test_zero_or_negative_authoritative_gap_confirms_no_siting_need():
    for gap in [0.0, -1.0]:
        gate = _build(s1_assessment=_assessment(status="meets", gap_value=gap))
        assert gate["state"] == "authoritative_need_not_confirmed"
        assert gate["required_site_count"] == 0


def test_sampled_inventory_keeps_need_unresolved():
    assessment = _assessment()
    assessment["complete_inventory"] = False
    gate = _build(s1_assessment=assessment)
    assert gate["state"] == "need_unresolved"
    assert "facility_inventory_incomplete" in gate["blockers"]


def test_missing_profile_or_capacity_gap_inputs_are_unresolved():
    assessment = _assessment()
    assessment["profile"]["status"] = "unavailable"
    gate = _build(s1_assessment=assessment)
    assert "authoritative_s1_metric_profile_missing" in gate["blockers"]
    capacity = _assessment(gap_type="facility_capacity_gap", gap_value=100)
    capacity["proposal_capacity_available"] = False
    gate = _build(s1_assessment=capacity)
    assert gate["state"] == "authoritative_need_confirmed"
    assert gate["required_site_count"] is None
    assert gate["gap_closure_assessed"] is False


def test_class_bundle_geography_and_timestamp_mismatches_fail_closed():
    assessment = _assessment()
    assessment["standard_class_id"] = "education.school"
    product = _s7_product()
    product["bundle_id"] = "other-bundle"
    product["snapshot_at"] = "2026-07-11T10:30:00+08:00"
    gate = _build(s1_assessment=assessment, s7_product=product, crosswalk_validation=_crosswalk("invalid"))
    for blocker in [
        "facility_class_mismatch",
        "facility_bundle_mismatch",
        "s1_assessment_older_than_s7_snapshot",
        "geography_crosswalk_invalid",
    ]:
        assert blocker in gate["blockers"]
    assert gate["state"] == "need_unresolved"


def test_gate_result_is_detached_from_inputs():
    assessment = _assessment()
    product = _s7_product()
    before_assessment = deepcopy(assessment)
    before_product = deepcopy(product)
    gate = _build(s1_assessment=assessment, s7_product=product)
    gate["gap"]["gap_value"] = 999
    assert assessment == before_assessment
    assert product == before_product
