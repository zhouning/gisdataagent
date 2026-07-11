from copy import deepcopy

from data_agent.uwm.traditional_livability_s6_s1_handoff import (
    build_s6_s1_handoff,
)
from data_agent.uwm.traditional_livability_facility_dictionary import (
    compute_canonical_content_digest,
)


def _analysis():
    original_input = {
        "facility_name": "和平便民市集",
        "raw_facility_type": "传统市集",
        "use_description": "社区日常零售服务",
    }
    original_input_digest = compute_canonical_content_digest(original_input)
    return {
        "schema": "uwm.traditional_livability.s6_analysis.v1",
        "analysis_id": "s6-example",
        "analyzed_at": "2026-07-11T12:00:00+08:00",
        "status": "potential_conflict_review_required",
        "max_claim_level": "spatial_screening_only",
        "normalized_request": {
            "analysis_area_id": "fulu_heping",
            "input_mode": "point",
            "longitude": 106.1,
            "latitude": 29.5,
            "facility_name": "和平便民市集",
            "raw_facility_type": "传统市集",
            "use_description": "社区日常零售服务",
            "confirmed_standard_class_id": "facility.market",
            "human_confirmation": {
                "schema": "uwm.traditional_livability.s6_human_confirmation.v1",
                "valid": True,
                "actor_id": "client-supplied-actor",
                "confirmed_at": "2026-07-11T11:58:00+08:00",
                "selected_standard_class_id": "facility.market",
                "original_input_digest": original_input_digest,
                "original_input": original_input,
                "dictionary_version": "liv-43-v1",
                "dictionary_content_digest": "sha256:dictionary",
                "selected_candidate": {
                    "standard_class_id": "facility.market",
                    "standard_class_label": "市场",
                    "match_method": "human_selected",
                    "evidence": [{"evidence_type": "reviewer_reason", "reason": "用途一致"}],
                },
            },
        },
        "executed_geography": {"planning_area_id": "fulu_heping", "scope": "fulu_sample"},
        "semantic_resolution": {
            "resolution_status": "human_confirmed",
            "confirmed_standard_class_id": "facility.market",
        },
        "human_confirmation_validation": {
            "valid": True,
            "actor_id": "client-supplied-actor",
            "confirmed_at": "2026-07-11T11:58:00+08:00",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": original_input_digest,
            "original_input": original_input,
            "dictionary_version": "liv-43-v1",
            "dictionary_content_digest": "sha256:dictionary",
            "selected_candidate": {
                "standard_class_id": "facility.market",
                "standard_class_label": "市场",
                "match_method": "human_selected",
                "evidence": [{"evidence_type": "reviewer_reason", "reason": "用途一致"}],
            },
            "validation_errors": [],
        },
        "screening": {"provider": "projected_planar_buffer", "distance_m": 150.0},
        "applied_rule_ids": [],
        "production_blockers": ["facility_inventory_sampled"],
        "completeness_warnings": ["facility_inventory_sampled"],
        "s1_handoff": {"ready": True, "confirmed_standard_class_id": "facility.market"},
        "geojson": {
            "proposed_geometry": {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [106.1, 29.5]},
                "properties": {},
            }
        },
        "source_bundle": {"bundle_id": "fulu-s6-v1", "complete_inventory": False},
    }


def _profiles():
    return {
        "schema": "uwm.traditional_livability.s1_metric_profile_collection.v1",
        "bundle_id": "fulu-s1-profile-v1",
        "profiles": [
            {
                "profile_id": "market-fpp-v1",
                "standard_class_id": "facility.market",
                "dimensions": ["FPP"],
                "status": "valid",
                "content_digest": "sha256:profile",
            }
        ],
    }


def test_handoff_digest_is_stable_for_equivalent_mapping_order():
    left = build_s6_s1_handoff(
        s6_analysis=_analysis(), metric_profiles=_profiles(), actor_id="alice", created_at="2026-07-11T12:01:00+08:00"
    )
    reordered = {key: value for key, value in reversed(list(_analysis().items()))}
    right = build_s6_s1_handoff(
        s6_analysis=reordered, metric_profiles=_profiles(), actor_id="alice", created_at="2026-07-11T12:01:00+08:00"
    )
    assert left["source_s6_analysis_digest"] == right["source_s6_analysis_digest"]
    assert left["handoff_id"] == right["handoff_id"]
    assert left["actor_id"] == "alice"
    assert left["confirmation"]["actor_id"] == "alice"
    assert left["ready_for_s1"] is True


def test_changed_proposal_invalidates_confirmation_binding():
    analysis = _analysis()
    analysis["normalized_request"]["facility_name"] = "已修改名称"
    result = build_s6_s1_handoff(
        s6_analysis=analysis, metric_profiles=_profiles(), actor_id="alice", created_at="2026-07-11T12:01:00+08:00"
    )
    assert result["ready_for_s1"] is False
    assert "stale_or_mismatched_human_confirmation" in result["validation_blockers"]


def test_missing_metric_profile_blocks_execution_without_fabrication():
    result = build_s6_s1_handoff(
        s6_analysis=_analysis(),
        metric_profiles={"profiles": []},
        actor_id="alice",
        created_at="2026-07-11T12:01:00+08:00",
    )
    assert result["ready_for_s1"] is False
    assert result["applicable_metric_profiles"] == []
    assert "authoritative_s1_metric_profile_missing" in result["validation_blockers"]


def test_result_is_detached_from_inputs():
    analysis = _analysis()
    profiles = _profiles()
    analysis_before = deepcopy(analysis)
    profiles_before = deepcopy(profiles)
    result = build_s6_s1_handoff(
        s6_analysis=analysis, metric_profiles=profiles, actor_id="alice", created_at="2026-07-11T12:01:00+08:00"
    )
    result["proposal"]["facility_name"] = "mutated"
    assert analysis == analysis_before
    assert profiles == profiles_before
