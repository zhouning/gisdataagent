import hashlib
import json

from scripts.audit_gwm_chicago_longitudinal_data_foundation import (
    DEFAULT_HISTORICAL_CROSSWALK_OUTPUT,
    DEFAULT_OUTPUT,
    RAW_EVIDENCE_FILES,
    ROOT,
    TARGET_POINT_WGS84,
    TARGET_TRACT_GEOID,
    audit_chicago_longitudinal_data_foundation,
    build_historical_event_crosswalk_artifact,
)


def test_bounded_chicago_data_foundation_evidence_is_internally_consistent():
    report = audit_chicago_longitudinal_data_foundation()

    assert report["status"] == (
        "bounded_evidence_valid_partial_outcome_panel_materialized"
    )
    assert report["summary"] == {
        "raw_artifact_count": 126,
        "check_count": 55,
        "passed_check_count": 55,
        "all_checks_passed": True,
    }
    assert set(report["artifacts"]) == set(RAW_EVIDENCE_FILES)
    assert all(check["passed"] is True for check in report["checks"].values())
    assert report["target"]["tract_geoid"] == TARGET_TRACT_GEOID
    assert report["target"]["point_wgs84"] == list(TARGET_POINT_WGS84)


def test_raw_evidence_hashes_and_checked_audit_report_are_reproducible():
    report = audit_chicago_longitudinal_data_foundation()
    checked = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    checked_crosswalk = json.loads(
        DEFAULT_HISTORICAL_CROSSWALK_OUTPUT.read_text(encoding="utf-8")
    )

    assert checked == report
    assert checked_crosswalk == build_historical_event_crosswalk_artifact(report)
    for artifact in report["artifacts"].values():
        payload = (ROOT / artifact["path"]).read_bytes()
        assert len(payload) == artifact["bytes"]
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]


def test_partial_real_data_progress_cannot_self_admit_a_panel_or_claim():
    report = audit_chicago_longitudinal_data_foundation()
    progress = report["source_role_progress"]

    assert progress["treatment_events"]["point_to_tract_verified"] is True
    assert progress["treatment_events"][
        "enacted_zoning_transition_verified"
    ] is True
    assert progress["treatment_events"]["legal_boundary_verified"] is True
    assert progress["treatment_events"]["machine_polygon_verified"] is False
    assert progress["treatment_events"]["effective_date_verified"] is False
    assert progress["treatment_events"][
        "complete_monthly_post_treatment_periods"
    ] == 0
    assert progress["treatment_events"][
        "temporally_viable_for_effect_estimation"
    ] is False
    assert progress["observed_outcomes"][
        "official_catalog_metadata_verified"
    ] is True
    assert progress["observed_outcomes"][
        "official_historical_schema_semantics_verified"
    ] is True
    assert progress["observed_outcomes"][
        "official_issue_date_fallback_semantics_verified"
    ] is True
    assert progress["observed_outcomes"][
        "official_contact_field_removal_semantics_verified"
    ] is True
    assert progress["observed_outcomes"]["row_schema_verified"] is True
    assert progress["observed_outcomes"]["row_sample_verified"] is True
    assert progress["observed_outcomes"]["bounded_treated_address_count"] == 17
    assert progress["observed_outcomes"]["bounded_permit_row_count"] == 70
    assert progress["observed_outcomes"][
        "bounded_post_publication_permit_row_count"
    ] == 18
    assert progress["observed_outcomes"][
        "complete_tract_permit_universe_verified"
    ] is False
    assert progress["observed_outcomes"][
        "untreated_control_outcomes_verified"
    ] is False
    assert progress["observed_outcomes"][
        "tract_month_outcome_panel_ready"
    ] is False
    assert progress["observed_outcomes"][
        "official_current_socrata_schema_verified"
    ] is True
    assert progress["observed_outcomes"]["license_verified"] is True
    assert progress["observed_outcomes"][
        "bounded_socrata_snapshot_row_count"
    ] == 114896
    assert progress["observed_outcomes"][
        "tract_month_outcome_panel_materialized"
    ] is True
    assert progress["observed_outcomes"][
        "spatially_admitted_permit_row_count"
    ] == 114816
    assert progress["observed_outcomes"][
        "spatially_unresolved_permit_row_count"
    ] == 72
    assert progress["observed_outcomes"][
        "state_plane_recovered_permit_row_count"
    ] == 1542
    assert progress["observed_outcomes"][
        "exact_address_geocoder_recovered_permit_row_count"
    ] == 44
    assert progress["observed_outcomes"][
        "pin_parcel_recovered_permit_row_count"
    ] == 0
    assert progress["observed_outcomes"][
        "facility_context_permit_row_count"
    ] == 26
    assert progress["observed_outcomes"][
        "candidate_control_outcomes_materialized"
    ] is True
    assert progress["time_varying_confounders"][
        "secondary_acs_sample_verified"
    ] is True
    assert progress["time_varying_confounders"][
        "official_acs_sample_verified"
    ] is False
    assert progress["interference_network"]["adjacency_constructed"] is True
    assert progress["interference_network"][
        "provisional_queen_adjacency_constructed"
    ] is True
    assert progress["interference_network"][
        "provisional_rook_adjacency_constructed"
    ] is True
    assert progress["interference_network"][
        "provisional_topology_quality_pass"
    ] is False
    assert progress["interference_network"][
        "provisional_interference_network_usable"
    ] is False
    assert progress["interference_network"][
        "official_adjacency_constructed"
    ] is True
    assert progress["interference_network"][
        "official_cook_internal_interference_network_usable"
    ] is True
    assert progress["interference_network"]["network_to_unit_time_ready"] is True
    assert progress["interference_network"]["official_city_tract_count"] == 801
    assert progress["interference_network"][
        "official_city_queen_edge_count"
    ] == 2636
    assert progress["interference_network"][
        "official_city_rook_edge_count"
    ] == 1889
    assert progress["interference_network"][
        "official_cook_dupage_city_internal_network_ready"
    ] is True
    assert progress["interference_network"][
        "outside_city_interference_ready"
    ] is False
    assert progress["spatial_units"][
        "official_cook_county_parcel_metadata_verified"
    ] is True
    assert progress["spatial_units"][
        "official_tiger2020_catalog_identity_verified"
    ] is True
    assert progress["spatial_units"][
        "official_tiger2020_iso_metadata_verified"
    ] is True
    assert progress["spatial_units"][
        "official_tiger2020_license_verified"
    ] is True
    assert progress["spatial_units"]["official_tiger2020_declared_crs"] == (
        "EPSG:4269"
    )
    assert progress["spatial_units"][
        "official_tiger2020_zip_accessible_in_browser"
    ] is True
    assert progress["spatial_units"][
        "official_tiger2020_archive_bytes_preserved"
    ] is False
    assert progress["spatial_units"]["official_tiger_geometry_verified"] is True
    assert progress["spatial_units"]["official_chicago_tract_count"] == 801
    assert progress["spatial_units"]["official_chicago_cook_tract_count"] == 799
    assert progress["spatial_units"]["official_chicago_dupage_tract_count"] == 2
    assert progress["spatial_units"][
        "official_target_parcel_sample_verified"
    ] is False
    assert report["admission"] == {
        "network_to_unit_time_ready": True,
        "official_cook_internal_interference_network_admitted": True,
        "official_cook_dupage_city_internal_network_admitted": True,
        "cross_county_city_internal_interference_network_admitted": True,
        "outside_city_interference_network_admitted": False,
        "observed_outcome_panel_materialized": True,
        "panel_materialization_ready": False,
        "panel_materialization_admitted": False,
        "causal_estimation_admitted": False,
        "effect_application_admitted": False,
    }
    assert report["claim_boundary"]["gwm_k0_validated"] is False
    assert report["claim_boundary"][
        "ordinance_legal_boundary_not_machine_polygon"
    ] is True
    assert report["claim_boundary"][
        "elms_last_publication_not_verified_effective_onset"
    ] is True
    assert report["claim_boundary"][
        "official_change_log_not_current_schema_or_rows"
    ] is True
    assert report["claim_boundary"][
        "historical_issue_date_completeness_not_current_row_validation"
    ] is True
    assert report["claim_boundary"][
        "building_records_address_history_not_complete_tract_outcome"
    ] is True
    assert report["claim_boundary"][
        "bounded_treated_address_outcomes_not_untreated_controls"
    ] is True
    assert report["claim_boundary"][
        "current_event_not_temporally_viable_for_monthly_effect_estimation"
    ] is True
    screening = report["historical_candidate_screening"]
    assert screening["candidate_record_numbers"] == [
        "O2024-0012247",
        "O2024-0012334",
        "O2024-0012532",
    ]
    assert screening["minimum_complete_post_publication_months"] == 19
    assert screening["temporal_screen_ready"] is True
    assert screening["final_attachment_metadata_ready"] is True
    assert screening["final_documents_downloaded"] is True
    assert screening["bounded_official_document_bytes"] == 2898496
    assert screening["final_document_evidence_ready"] is True
    assert screening["legal_boundary_text_ready"] is True
    assert screening["zoning_transition_text_ready"] is True
    assert screening["official_point_addresses_ready"] is True
    assert screening["official_pins_ready"] is True
    assert screening["point_to_tract_crosswalks_ready"] is True
    assert screening["current_zoning_map_polygons_ready"] is True
    expanded = screening["expanded_preregistered_cohort"]
    assert expanded["source_row_count"] == 290
    assert expanded["selected_event_count"] == 23
    assert expanded["zoning_map_ready_count"] == 22
    assert expanded["point_address_ready_count"] == 19
    assert expanded["tract_crosswalk_ready_count"] == 19
    assert expanded["current_parcel_crosswalk_ready_count"] == 19
    assert expanded["joint_spatial_crosswalk_ready_count"] == 17
    assert expanded["missing_zoning_map_records"] == ["O2024-0013362"]
    assert expanded["point_polygon_mismatch_records"] == ["O2024-0012332"]
    assert expanded["cohort_crosswalk_complete"] is False
    assert expanded["outcome_panel_ready"] is False
    assert expanded["causal_estimation_ready"] is False
    assert report["source_role_progress"]["observed_outcomes"][
        "public_way_permits_rejected_as_building_outcome"
    ] is True
    assert report["source_role_progress"]["spatial_units"][
        "city_census_tract_candidate_year"
    ] == 2000
    assert report["source_role_progress"]["spatial_units"][
        "city_census_tract_candidate_rejected_for_2020_panel"
    ] is True
    assert {
        event["tract_geoid"]
        for event in screening["event_crosswalks"].values()
    } == {"17031243400", "17031300900", "17031830600"}
    assert all(
        event["validation"]["passed"] is True
        for event in screening["event_crosswalks"].values()
    )
    assert all(
        event["zoning_map_validation"]["passed"] is True
        for event in screening["event_crosswalks"].values()
    )
    assert screening["event_crosswalks"]["O2024-0012247"][
        "zoning_map_polygon"
    ]["area_ratio_to_legal_lot"] == 1.365344
    assert screening["event_crosswalks"]["O2024-0012532"][
        "zoning_map_polygon"
    ]["area_ratio_to_legal_lot"] == 1.403035
    assert screening["machine_treatment_geometries_ready"] is False
    assert screening["effective_onsets_ready"] is False
    assert screening["source_and_crosswalk_ready"] is False
    assert screening["cohort_panel_ready"] is False
    assert screening["causal_estimation_ready"] is False
    assert report["claim_boundary"][
        "historical_matter_metadata_not_cohort_panel"
    ] is True
    assert report["claim_boundary"][
        "historical_legal_boundary_text_not_machine_geometry"
    ] is True
