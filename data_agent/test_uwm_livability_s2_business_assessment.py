from pathlib import Path

from data_agent.uwm.livability_s2.business_assessment import assess_s2_business_impact
from data_agent.uwm.livability_s2.scenario_service import S2ScenarioService


PRODUCT_DIR = (
    Path(__file__).resolve().parents[1]
    / "data/uwm_public_proxy/chongqing_central/uwm_livability_s2_fulu"
)
TARGET_PARCEL_ID = "parcel_79bb3178da33949459fc"


def _real_bundle():
    return S2ScenarioService(PRODUCT_DIR)._load_bundle()


def test_land_use_change_without_facility_action_fails_closed_on_real_data():
    bundle = _real_bundle()
    result = assess_s2_business_impact(
        parcels=bundle["parcels"],
        facilities=bundle["facilities"],
        parcel_id=TARGET_PARCEL_ID,
        action_type="change_land_use",
        facility_class=None,
        facility_id=None,
        service_radius_m=None,
        radius_evidence_source=None,
        critical_facility=False,
        facility_inventory_complete=False,
        transition_status="unresolved",
    )

    assert result["recommendation"] == "evidence_insufficient"
    assert "facility_action_not_defined_for_land_use_change" in result["blockers"]
    assert result["baseline"] is None
    assert result["population_coverage_claim"] is False


def test_add_facility_computes_reproducible_real_parcel_coverage_proxy():
    bundle = _real_bundle()
    kwargs = dict(
        parcels=bundle["parcels"],
        facilities=bundle["facilities"],
        parcel_id=TARGET_PARCEL_ID,
        action_type="add_facility",
        facility_class="education.school",
        facility_id=None,
        service_radius_m=500.0,
        radius_evidence_source="user_scenario_assumption",
        critical_facility=False,
        facility_inventory_complete=False,
        transition_status="allowed",
    )
    first = assess_s2_business_impact(**kwargs)
    second = assess_s2_business_impact(**kwargs)

    assert first["baseline"]["facility_count"] == 0
    assert first["intervention"]["facility_count"] == 1
    assert first["intervention"]["covered_parcel_count"] > 0
    assert first["coverage_delta_percentage_points"] > 0
    assert TARGET_PARCEL_ID in first["newly_covered_parcel_ids"]
    assert first["recommendation"] == "conditional_agree"
    assert first["action"]["critical_facility"] is True
    assert first["action"]["criticality_source"] == "versioned_business_rule"
    assert first["business_rule_version"] == "s2-business-rules-2026.07.14.1"
    assert first["evidence_level"] == "bounded_scenario_proxy"
    assert first["population_coverage_claim"] is False
    assert first["assessment_digest"] == second["assessment_digest"]
    assert first["intervention"]["service_areas"]["features"]


def test_real_service_run_binds_business_assessment_to_uwm_and_map_evidence():
    service = S2ScenarioService(PRODUCT_DIR)
    parcel = service.parcel_detail(TARGET_PARCEL_ID)["parcel"]
    eldercare_project = next(
        project
        for project in service.list_planning_projects()["projects"]
        if project["project_name"] == "养老服务站"
    )
    run = service.rollout(
        parcel_id=TARGET_PARCEL_ID,
        from_land_use_class=parcel["properties"]["current_land_use_class"],
        to_land_use_class="village_public_service_land",
        snapshot_digest=service.catalog()["snapshot_digest"],
        rationale="真实地块新增学校覆盖与UWM联合推演",
        requested_at="2026-07-13T12:00:00Z",
        actor_id="authenticated-planner",
        alternative_land_use_class=None,
        action_type="add_facility",
        facility_class="eldercare.station",
        service_radius_m=500.0,
        radius_evidence_source="user_scenario_assumption",
        critical_facility=True,
        planning_project_id=eldercare_project["project_id"],
    )

    assessment = run["business_assessment"]
    assert assessment["recommendation"] == "conditional_agree"
    assert assessment["planning_project_evidence"]["project_name"] == "养老服务站"
    assert assessment["planning_project_evidence"]["coverage_eligible"] is False
    assert assessment["coverage_delta_percentage_points"] > 0
    assert run["rollout"]["intervention"]["t1"]["direct_state_delta"]["to_land_use_class"] == "village_public_service_land"
    assert run["rollout"]["intervention"]["t1"]["direct_state_delta"]["state_semantics"] == "action_conditioned_scenario_state"
    assert run["rollout"]["intervention"]["t1"]["direct_state_delta"]["observed_outcome"] is False
    assert run["technical_audit"]["world_model_classification"]["geospatial_state_graph"] is True
    assert run["technical_audit"]["world_model_classification"]["empirical_intervention_effect"] is False
    assert run["technical_audit"]["result_attribution"]["coverage_proxy_is_not_t2_message_count"] is True
    assert run["map_evidence"]["intervention_service_areas"]["features"]
    assert run["map_evidence"]["newly_covered_parcels"]["features"]
