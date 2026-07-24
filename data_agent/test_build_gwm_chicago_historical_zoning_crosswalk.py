import hashlib
import json

from scripts.build_gwm_chicago_historical_zoning_crosswalk import (
    DEFAULT_OUTPUT,
    RETRY_FILES,
    ROOT,
    build_historical_zoning_crosswalk,
)


EXPECTED_UNMATCHED = {
    "O2024-0008445",
    "O2024-0008449",
    "O2024-0009011",
    "O2024-0009013",
}


def test_preregistered_cohort_spatial_crosswalk_is_partial_and_fail_closed():
    crosswalk = build_historical_zoning_crosswalk()
    summary = crosswalk["summary"]

    assert summary["cohort_event_count"] == 23
    assert summary["zoning_map_ready_count"] == 22
    assert summary["missing_zoning_map_records"] == ["O2024-0013362"]
    assert summary["point_address_ready_count"] == 19
    assert summary["tract_crosswalk_ready_count"] == 19
    assert summary["current_parcel_crosswalk_ready_count"] == 19
    assert set(summary["unmatched_point_address_records"]) == EXPECTED_UNMATCHED
    assert summary["joint_spatial_crosswalk_ready_count"] == 17
    assert summary["parcel_augmented_spatial_crosswalk_ready_count"] == 17
    assert summary["point_polygon_mismatch_records"] == ["O2024-0012332"]
    assert all(
        event["tract_crosswalk"]["ready"]
        == event["point_address"]["ready"]
        for event in crosswalk["events"]
    )
    assert all(
        event["current_parcel_crosswalk"]["ready"]
        == event["point_address"]["ready"]
        for event in crosswalk["events"]
    )
    assert all(
        not event["zoning_map"]["machine_legal_parcel_polygon_verified"]
        for event in crosswalk["events"]
    )
    assert crosswalk["readiness"]["zoning_map_crosswalk_complete"] is False
    assert crosswalk["readiness"][
        "partial_zoning_map_crosswalk_available"
    ] is True
    assert crosswalk["readiness"]["point_address_crosswalk_complete"] is False
    assert crosswalk["readiness"]["tract_crosswalk_complete"] is False
    assert crosswalk["readiness"]["current_parcel_crosswalk_complete"] is False
    assert crosswalk["readiness"][
        "partial_current_parcel_crosswalk_available"
    ] is True
    assert crosswalk["readiness"]["joint_spatial_crosswalk_complete"] is False
    assert crosswalk["readiness"][
        "partial_joint_spatial_crosswalk_available"
    ] is True
    assert crosswalk["readiness"][
        "partial_point_and_tract_crosswalk_available"
    ] is True
    assert crosswalk["readiness"]["outcome_panel_ready"] is False
    assert crosswalk["readiness"]["causal_estimation_ready"] is False


def test_unmatched_events_survive_with_retry_negative_evidence():
    crosswalk = build_historical_zoning_crosswalk()
    events = {event["record_number"]: event for event in crosswalk["events"]}

    assert set(RETRY_FILES) == EXPECTED_UNMATCHED
    for record_number in EXPECTED_UNMATCHED:
        event = events[record_number]
        assert event["point_address"]["ready"] is False
        assert event["tract_crosswalk"]["ready"] is False
        retry = event["point_address"]["retry_observation"]
        assert retry["exact_point_address_recovered"] is False
        assert retry["exact_candidate_count"] == 0


def test_multi_polygon_event_and_missing_zoning_event_are_not_conflated():
    crosswalk = build_historical_zoning_crosswalk()
    events = {event["record_number"]: event for event in crosswalk["events"]}

    multi = events["O2024-0008868"]["zoning_map"]
    assert multi["ready"] is True
    assert multi["feature_count"] == 2
    assert multi["zone_classes"] == ["C1-3", "RM-4.5"]

    missing = events["O2024-0013362"]["zoning_map"]
    assert missing["ready"] is False
    assert missing["feature_count"] == 0

    mismatch = events["O2024-0012332"]["spatial_consistency"]
    assert mismatch["ready"] is False
    assert mismatch["point_and_zoning_individually_ready"] is True
    assert mismatch["point_inside_event_zoning_polygon"] is False
    assert mismatch["point_context_observation"] == {
        "artifact": "chicago_current_zoning_point_context_O2024_0012332.json",
        "feature_count": 1,
        "zone_class": "B3-2",
        "clerk_document_number": None,
        "ordinance_number": None,
    }


def test_current_parcel_geometry_matches_seed_legal_areas_but_not_vintage():
    crosswalk = build_historical_zoning_crosswalk()
    events = {event["record_number"]: event for event in crosswalk["events"]}

    race = events["O2024-0012247"]["current_parcel_crosswalk"]
    bosworth = events["O2024-0012532"]["current_parcel_crosswalk"]
    assert race["area_ratio_to_legal_lot"] == 1.000635
    assert bosworth["area_ratio_to_legal_lot"] == 0.998304
    assert race["area_within_one_percent_of_legal_lot"] is True
    assert bosworth["area_within_one_percent_of_legal_lot"] is True
    assert all(
        event["current_parcel_crosswalk"]["historical_vintage_verified"]
        is False
        for event in crosswalk["events"]
    )
    assert all(
        event["current_parcel_crosswalk"][
            "machine_legal_treatment_polygon_verified"
        ]
        is False
        for event in crosswalk["events"]
    )


def test_checked_crosswalk_and_all_artifact_hashes_are_reproducible():
    crosswalk = build_historical_zoning_crosswalk()
    checked = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert checked == crosswalk
    assert len(crosswalk["crosswalk_digest"]) == 64
    for artifact in crosswalk["artifacts"].values():
        payload = (ROOT / artifact["path"]).read_bytes()
        assert len(payload) == artifact["bytes"]
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]
