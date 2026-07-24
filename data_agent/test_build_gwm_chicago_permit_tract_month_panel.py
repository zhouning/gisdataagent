import json

from shapely.geometry import box

from scripts.build_gwm_chicago_permit_tract_month_panel import (
    DEFAULT_OUTPUT,
    _assign_rows_to_tracts,
    _source_tract_geoid,
    build_permit_tract_month_panel,
)
from scripts.build_gwm_chicago_unresolved_permit_geocoder_request import (
    DEFAULT_DIAGNOSTIC_OUTPUT,
    DEFAULT_REQUEST_OUTPUT,
    build_unresolved_permit_geocoder_request,
)
from scripts.adjudicate_gwm_chicago_remaining_permit_spatial_evidence import (
    DEFAULT_OUTPUT as DEFAULT_REMAINING_ADJUDICATION_OUTPUT,
    adjudicate_remaining_permit_spatial_evidence,
)


def test_checked_permit_tract_month_panel_is_reproducible_and_zero_filled():
    result = build_permit_tract_month_panel()
    checked = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert checked == result
    assert result["query_contract"]["row_count"] == 114896
    assert result["panel_summary"] == {
        "candidate_control_tract_count": 700,
        "cohort_role_counts": {
            "candidate_control_outside_queen_buffer": 700,
            "interference_buffer_queen_neighbor": 84,
            "treated_event_tract": 17,
        },
        "month_count": 42,
        "panel_row_count": 33642,
        "permit_count": 114816,
        "race_crosscheck": {
            "address": "1228 W RACE AVE",
            "current_2020_tract_geoid": "17031243400",
            "legacy_rows_require_point_reassignment": True,
            "observed_source_tract_values": ["2434", "243400"],
            "post_2020_rows_match_official_crosswalk": True,
            "row_count": 5,
        },
        "target_event_tract_count": 17,
        "unit_count": 801,
        "zero_cell_count": 5308,
    }
    panel = result["panel"]
    assert len({(row["tract_geoid"], row["month"]) for row in panel}) == 33642
    assert sum(row["permit_count"] for row in panel) == 114816
    diagnostics = result["assignment_diagnostics"]
    assert diagnostics["admitted_row_count"] == 114816
    assert diagnostics["unresolved_row_count"] == 72
    assert diagnostics["state_plane_candidate_count"] == 1629
    assert diagnostics["address_geocoder_candidate_count"] == 44
    assert diagnostics["assignment_method_counts"][
        "state_plane_recovers_missing_or_legacy_source_code"
    ] == 1542
    assert diagnostics["assignment_method_counts"][
        "address_geocoder_recovers_missing_or_legacy_source_code"
    ] == 44
    supplement = result["query_contract"][
        "missing_coordinate_supplement_validation"
    ]
    assert supplement["row_count"] == 1856
    assert supplement["state_plane_xy_present_count"] == 1672
    assert supplement["public_street_number_and_name_present_count"] == 1853
    geocoder = result["query_contract"]["unresolved_geocoder_validation"]
    assert geocoder["response_location_count"] == 47
    assert geocoder["exact_score_100_point_address_count"] == 8
    assert geocoder["exact_score_100_recovered_row_count"] == 44
    assert geocoder["fuzzy_point_address_count"] == 4
    assert geocoder["unmatched_address_count"] == 35
    assert geocoder["fuzzy_matches_admitted"] is False
    assert result["readiness"]["tract_month_panel_materialized"] is True
    assert result["readiness"]["complete_spatial_assignment_ready"] is False
    assert result["readiness"]["causal_estimation_ready"] is False


def test_source_tract_normalization_zero_pads_but_rejects_unknown_vintages():
    official = {"17031010400", "17031243400"}

    assert _source_tract_geoid("10400", official) == "17031010400"
    assert _source_tract_geoid("010400", official) == "17031010400"
    assert _source_tract_geoid("243400", official) == "17031243400"
    assert _source_tract_geoid("2434", official) is None
    assert _source_tract_geoid(None, official) is None


def test_point_assignment_overrides_conflicting_source_and_never_imputes_unknown():
    rows = [
        {
            "id": "1",
            "permit_": "P1",
            "issue_date": "2024-01-15T00:00:00.000",
            "application_start_date": "2024-01-01T00:00:00.000",
            "census_tract": "020000",
            "latitude": "0.5",
            "longitude": "0.5",
        },
        {
            "id": "2",
            "permit_": "P2",
            "issue_date": "2024-01-16T00:00:00.000",
            "application_start_date": None,
            "census_tract": None,
            "latitude": None,
            "longitude": None,
        },
    ]
    assignment = _assign_rows_to_tracts(
        rows=rows,
        tract_geoids=["17031010000", "17031020000"],
        tract_geometries=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
        city_tracts={"17031010000", "17031020000"},
    )

    assert assignment["admitted_rows"][0]["assigned_geoid"] == "17031010000"
    assert assignment["admitted_rows"][0]["assignment_method"] == (
        "point_overrides_conflicting_source_code"
    )
    assert assignment["summary"]["direct_point_conflict_count"] == 1
    assert assignment["summary"]["assignment_method_counts"]["unresolved"] == 1
    assert assignment["unresolved_rows"] == [
        {
            "id": "2",
            "permit_": "P2",
            "census_tract": None,
            "latitude": None,
            "longitude": None,
        }
    ]


def test_checked_unresolved_geocoder_request_is_deduplicated_and_fail_closed():
    request, diagnostic = build_unresolved_permit_geocoder_request()
    checked_request = json.loads(DEFAULT_REQUEST_OUTPUT.read_text(encoding="utf-8"))
    checked_diagnostic = json.loads(
        DEFAULT_DIAGNOSTIC_OUTPUT.read_text(encoding="utf-8")
    )

    assert request == checked_request
    assert diagnostic == checked_diagnostic
    assert len(request["records"]) == 47
    recovery = diagnostic["recovery_ladder"]
    assert recovery["initial_unresolved_without_valid_wgs84_or_2020_tract"] == 1658
    assert recovery["state_plane_recovered_initially_unresolved_count"] == 1542
    assert recovery["remaining_unresolved_row_count"] == 116
    assert recovery["remaining_unique_public_project_address_count"] == 47
    assert diagnostic["missingness_structure"][
        "express_program_missingness_concentrated"
    ] is True
    assert diagnostic["missingness_structure"]["missingness_assumed_random"] is False
    assert diagnostic["readiness"]["address_geocoder_response_ready"] is False
    assert diagnostic["claim_boundary"]["geocoder_request_not_geocoder_result"] is True


def test_checked_remaining_pin_and_facility_evidence_stays_fail_closed():
    result = adjudicate_remaining_permit_spatial_evidence()
    checked = json.loads(
        DEFAULT_REMAINING_ADJUDICATION_OUTPUT.read_text(encoding="utf-8")
    )

    assert result == checked
    pin = result["pin_parcel_adjudication"]
    assert pin["pin_bearing_row_count"] == 14
    assert pin["requested_unique_pin_count"] == 14
    assert pin["returned_unique_pin_polygon_count"] == 11
    assert pin["address_consistent_row_count"] == 0
    assert pin["admitted_row_count"] == 0
    facility = result["facility_context"]
    assert facility["official_name"] == "O'Hare Airport"
    assert facility["official_point_tract_geoid"] == "17043840000"
    assert facility["context_row_count"] == 26
    assert facility["facility_context_ready"] is True
    assert facility["permit_tract_assignment_admitted"] is False
    assert result["readiness"]["complete_spatial_assignment_ready"] is False
