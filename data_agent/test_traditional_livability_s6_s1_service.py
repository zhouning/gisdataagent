import pytest
from shapely.geometry import Point, mapping

from data_agent.test_traditional_livability_s1_comparison import (
    _demand_units,
    _facility_product,
    _matrix,
    _profile,
)
from data_agent.test_traditional_livability_s6_s1_handoff import _analysis
from data_agent.uwm.traditional_livability_s6_s1_service import (
    HandoffConflict,
    HandoffNotFound,
    TraditionalLivabilityS6S1Service,
)


def _profiles():
    profile = {**_profile(), "profile_bundle_id": "profile-bundle-v1"}
    return {
        "schema": "uwm.traditional_livability.s1_metric_profile_collection.v1",
        "status": "ready",
        "bundle_id": "profile-bundle-v1",
        "profiles": [profile],
    }


def _service():
    return TraditionalLivabilityS6S1Service(
        facility_product=_facility_product(),
        demand_units=_demand_units(),
        metric_profiles=_profiles(),
        synthesis_matrices={"matrix-v1": _matrix()},
    )


def _service_analysis():
    analysis = _analysis()
    analysis["source_bundle"] = {"bundle_id": "facility-bundle-v1", "complete_inventory": True}
    analysis["normalized_request"]["analysis_area_id"] = "area-1"
    analysis["executed_geography"]["planning_area_id"] = "area-1"
    analysis["geojson"]["proposed_geometry"] = {
        "type": "Feature",
        "geometry": mapping(Point(106.1, 29.5)),
        "properties": {},
    }
    return analysis


def test_create_binds_actor_and_get_is_owner_only():
    service = _service()
    handoff = service.create_handoff(
        s6_analysis=_service_analysis(), actor_id="alice", created_at="2026-07-11T12:01:00+08:00"
    )
    assert handoff["actor_id"] == "alice"
    assert handoff["confirmation"]["actor_id"] == "alice"
    assert service.get_handoff(handoff["handoff_id"], actor_id="alice") == handoff
    with pytest.raises(HandoffNotFound):
        service.get_handoff(handoff["handoff_id"], actor_id="bob")


def test_other_actor_cannot_execute_handoff():
    service = _service()
    handoff = service.create_handoff(
        s6_analysis=_service_analysis(), actor_id="alice", created_at="2026-07-11T12:01:00+08:00"
    )
    with pytest.raises(HandoffNotFound):
        service.execute_s1(handoff["handoff_id"], actor_id="bob")


def test_execute_returns_static_baseline_and_proposal_comparison():
    service = _service()
    handoff = service.create_handoff(
        s6_analysis=_service_analysis(), actor_id="alice", created_at="2026-07-11T12:01:00+08:00"
    )
    result = service.execute_s1(handoff["handoff_id"], actor_id="alice")
    assert result["method"] == "deterministic_static_proposal_comparison"
    assert result["claim_boundary"]["uwm_rollout"] is False
    assert result["handoff_id"] == handoff["handoff_id"]


def test_unready_handoff_cannot_execute():
    service = TraditionalLivabilityS6S1Service(
        facility_product=_facility_product(),
        demand_units=_demand_units(),
        metric_profiles={"profiles": []},
        synthesis_matrices={},
    )
    handoff = service.create_handoff(
        s6_analysis=_service_analysis(), actor_id="alice", created_at="2026-07-11T12:01:00+08:00"
    )
    assert handoff["ready_for_s1"] is False
    with pytest.raises(HandoffConflict, match="handoff_not_ready_for_s1"):
        service.execute_s1(handoff["handoff_id"], actor_id="alice")


def test_profile_bundle_change_after_creation_fails_closed():
    service = _service()
    handoff = service.create_handoff(
        s6_analysis=_service_analysis(), actor_id="alice", created_at="2026-07-11T12:01:00+08:00"
    )
    service.metric_profiles["bundle_id"] = "profile-bundle-v2"
    with pytest.raises(HandoffConflict, match="metric_profile_bundle_mismatch"):
        service.execute_s1(handoff["handoff_id"], actor_id="alice")


def test_service_loads_evidence_bounded_product_directory(tmp_path):
    from data_agent.test_build_traditional_livability_s6_s1_fulu import _facility_product, _s6_resources
    from data_agent.uwm.traditional_livability_s6_s1_product import build_s6_s1_product_bundle

    build_s6_s1_product_bundle(
        facility_product=_facility_product(), s6_resources=_s6_resources(), output_dir=tmp_path
    )
    service = TraditionalLivabilityS6S1Service.from_product_dir(tmp_path)
    assert service.list_profiles()["status"] == "unavailable"
    assert service.facility_product["bundle_id"].startswith("traditional-livability-s6-s1-")
