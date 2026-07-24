from copy import deepcopy
import hashlib
import json
from pathlib import Path

from data_agent.uwm.geospatial_kernel import (
    LONGITUDINAL_DESIGN_GATES,
    LONGITUDINAL_ESTIMATION_GATES,
    LONGITUDINAL_PANEL_CROSSWALK_GATES,
    LONGITUDINAL_PANEL_SOURCE_ROLES,
    build_longitudinal_panel_source_contract,
    seed_spatiotemporal_gate_evidence_from_panel_sources,
    validate_longitudinal_panel_source_contract,
)
from scripts.build_gwm_chicago_longitudinal_panel_source_candidate import (
    DEFAULT_OUTPUT,
    EVIDENCE_FILES,
    ROOT,
    build_chicago_longitudinal_panel_source_candidate,
)


def _source(role: str) -> dict:
    return {
        "source_id": f"source-{role}",
        "role": role,
        "publisher": "Official test publisher",
        "canonical_url": f"https://example.test/{role}",
        "platform": "test_api",
        "authority_status": "verified_official",
        "access_boundary": "none",
        "metadata_probe_status": "pass",
        "schema_probe_status": "pass",
        "license_status": "pass",
        "time_coverage_status": "pass",
        "geography_coverage_status": "pass",
        "sample_validation_status": "pass",
        "stable_id_fields": [f"{role}_id"],
        "time_fields": ["observed_at"],
        "geometry_fields": ["geometry"],
        "temporal_semantics": "event_time",
        "evidence_refs": [f"evidence:{role}"],
    }


def _contract(
    *,
    crosswalks_ready: bool = True,
    extra_sources: list[dict] | None = None,
) -> dict:
    sources = [_source(role) for role in LONGITUDINAL_PANEL_SOURCE_ROLES]
    sources.extend(extra_sources or [])
    return build_longitudinal_panel_source_contract(
        candidate={
            "candidate_id": "complete-source-fixture",
            "domain_instance": "UWM_fixture",
            "geography": "test geography",
            "target_unit": "tract",
            "target_cadence": "monthly",
            "treatment_definition": "observed enacted intervention",
            "outcome_definition": "observed outcome events",
        },
        sources=sources,
        crosswalk_evidence={
            gate: {
                "passed": crosswalks_ready,
                "evidence_refs": [f"evidence:{gate}"] if crosswalks_ready else [],
            }
            for gate in LONGITUDINAL_PANEL_CROSSWALK_GATES
        },
        probe_policy={
            "probe_only": True,
            "full_download_authorized": False,
            "bulk_download_performed": False,
            "training_panel_materialized": False,
        },
        provenance={
            "top_level_skill": "urban-data-seeker",
            "route_type": "test_route",
            "selected_skills": ["legistar-platform", "socrata-platform"],
            "probed_at": "2026-07-23T00:00:00Z",
        },
    )


def test_complete_sources_only_make_materialization_ready_not_admitted():
    contract = _contract()
    validation = validate_longitudinal_panel_source_contract(contract)

    assert validation["valid"] is True
    assert validation["all_source_metadata_ready"] is True
    assert validation["all_source_samples_ready"] is True
    assert validation["all_crosswalks_ready"] is True
    assert validation["panel_materialization_ready"] is True
    assert validation["panel_materialization_admitted"] is False
    assert validation["causal_estimation_admitted"] is False
    assert validation["effect_application_admitted"] is False
    assert validation["general_geospatial_kernel_validated"] is False
    assert validation["gwm_k0_validated"] is False


def test_missing_outcome_role_cannot_be_compensated_by_other_sources():
    contract = _contract()
    contract["sources"] = [
        source for source in contract["sources"] if source["role"] != "observed_outcomes"
    ]
    validation = validate_longitudinal_panel_source_contract(contract)

    assert validation["valid"] is False
    assert "source_role_missing:observed_outcomes" in validation["errors"]
    assert validation["panel_materialization_admitted"] is False


def test_multiple_sources_for_one_role_are_allowed_but_all_must_be_ready():
    second_confounder = _source("time_varying_confounders")
    second_confounder["source_id"] = "source-time-varying-weather"
    validation = validate_longitudinal_panel_source_contract(
        _contract(extra_sources=[second_confounder])
    )
    assert validation["valid"] is True
    assert validation["role_readiness"]["time_varying_confounders"][
        "source_ids"
    ] == [
        "source-time-varying-weather",
        "source-time_varying_confounders",
    ]
    assert validation["panel_materialization_ready"] is True

    second_confounder["metadata_probe_status"] = "blocked"
    validation = validate_longitudinal_panel_source_contract(
        _contract(extra_sources=[second_confounder])
    )
    assert validation["valid"] is True
    assert validation["role_readiness"]["time_varying_confounders"][
        "metadata_ready"
    ] is False
    assert validation["panel_materialization_ready"] is False


def test_passed_source_probe_requires_evidence_and_stable_time_identity():
    contract = _contract()
    treatment = next(
        source for source in contract["sources"] if source["role"] == "treatment_events"
    )
    treatment["evidence_refs"] = []
    treatment["stable_id_fields"] = []
    treatment["time_fields"] = []
    validation = validate_longitudinal_panel_source_contract(contract)

    assert validation["valid"] is False
    assert "sources_4_metadata_pass_requires_evidence_refs" in validation["errors"]
    assert "sources_4_sample_pass_requires_stable_ids" in validation["errors"]
    assert "sources_4_sample_pass_requires_time_fields" in validation["errors"]


def test_probe_contract_cannot_self_authorize_bulk_download_or_training_panel():
    contract = _contract()
    contract["probe_policy"]["full_download_authorized"] = True
    contract["probe_policy"]["bulk_download_performed"] = True
    contract["probe_policy"]["training_panel_materialized"] = True
    validation = validate_longitudinal_panel_source_contract(contract)

    assert validation["valid"] is False
    assert "probe_policy_full_download_authorized_must_be_false" in validation[
        "errors"
    ]
    assert "probe_policy_bulk_download_requires_non_probe_mode" in validation[
        "errors"
    ]
    assert "probe_policy_bulk_download_requires_bounded_authorization" in validation[
        "errors"
    ]
    assert "probe_policy_training_panel_materialized_must_be_false" in validation[
        "errors"
    ]


def test_chicago_candidate_admits_treatment_sample_but_not_panel_sources():
    contract = build_chicago_longitudinal_panel_source_candidate()
    validation = validate_longitudinal_panel_source_contract(contract)

    assert validation["valid"] is True
    assert contract["candidate"]["target_unit"] == "2020_census_tract"
    treatment = validation["role_readiness"]["treatment_events"]
    assert treatment["source_ids"] == ["chicago_elms_zoning_reclassification"]
    assert treatment["sample_ready"] is False
    treatment_source = next(
        source for source in contract["sources"] if source["role"] == "treatment_events"
    )
    assert treatment_source["sample_validation_status"] == "pass"
    assert treatment_source["probe_observations"]["status"] == "90-Final"
    assert treatment_source["probe_observations"]["sub_status"] == "Passed"
    assert treatment_source["probe_observations"]["effective_date_verified"] is False
    assert treatment_source["probe_observations"]["treatment_polygon_verified"] is False
    assert treatment_source["probe_observations"][
        "legal_treatment_boundary_verified"
    ] is True
    assert treatment_source["probe_observations"][
        "machine_treatment_polygon_verified"
    ] is False
    assert treatment_source["probe_observations"]["enacted_from_zoning"] == "RS-3"
    assert treatment_source["probe_observations"]["enacted_to_zoning"] == "RM-4.5"
    assert treatment_source["probe_observations"][
        "official_point_address_verified"
    ] is True
    assert treatment_source["probe_observations"]["official_point_address_pin"] == (
        "2020302029"
    )
    assert treatment_source["probe_observations"]["fcc_2020_census_tract_geoid"] == (
        "17031671600"
    )
    assert treatment_source["probe_observations"][
        "current_zoning_is_treatment_polygon"
    ] is False
    assert treatment_source["probe_observations"][
        "latest_attachment_bytes_transferred"
    ] == 318554
    assert treatment_source["probe_observations"][
        "official_cook_county_parcel_metadata_verified"
    ] is True
    assert treatment_source["probe_observations"][
        "official_cook_county_target_pin_sample_verified"
    ] is False
    assert treatment_source["probe_observations"][
        "complete_monthly_post_treatment_periods"
    ] == 0
    assert treatment_source["probe_observations"][
        "temporally_viable_for_effect_estimation"
    ] is False
    assert validation["all_source_metadata_ready"] is False
    assert validation["all_source_samples_ready"] is False
    assert validation["panel_materialization_admitted"] is False
    assert contract["probe_policy"]["bounded_bulk_download_authorized"] is True
    assert contract["probe_policy"]["bulk_download_performed"] is True
    assert contract["probe_policy"]["outcome_panel_materialized"] is True
    assert contract["probe_policy"]["training_panel_materialized"] is False
    assert contract["probe_policy"]["attachment_saved_to_project"] is True
    assert contract["probe_policy"][
        "bounded_official_documents_saved_to_project"
    ] is True
    assert contract["probe_policy"]["single_attachment_full_transfer_to_null"] is True
    assert contract["provenance"][
        "network_requests_bounded_to_metadata_and_samples"
    ] is False


def test_chicago_candidate_preserves_access_boundaries_and_acs_temporal_warning():
    contract = build_chicago_longitudinal_panel_source_candidate()
    sources = {source["role"]: source for source in contract["sources"]}

    assert sources["observed_outcomes"]["access_boundary"] == "browser_or_waf"
    assert sources["observed_outcomes"]["metadata_probe_status"] == "pass"
    assert sources["observed_outcomes"]["schema_probe_status"] == "pass"
    assert sources["observed_outcomes"]["sample_validation_status"] == "pass"
    assert sources["observed_outcomes"]["time_coverage_status"] == "pass"
    assert sources["observed_outcomes"]["license_status"] == "pass"
    assert sources["observed_outcomes"]["probe_observations"][
        "datagov_catalog_organization"
    ] == "City of Chicago"
    assert sources["observed_outcomes"]["probe_observations"][
        "row_sample_verified"
    ] is True
    assert sources["observed_outcomes"]["probe_observations"][
        "official_historical_schema_semantics_verified"
    ] is True
    assert sources["observed_outcomes"]["probe_observations"][
        "official_issue_date_fallback_semantics_verified"
    ] is True
    assert sources["observed_outcomes"]["probe_observations"][
        "issue_date_is_not_construction_start"
    ] is True
    assert sources["observed_outcomes"]["probe_observations"][
        "bulk_contact_fields_intentionally_removed_for_privacy"
    ] is True
    assert sources["observed_outcomes"]["probe_observations"][
        "row_schema_verified"
    ] is True
    assert sources["observed_outcomes"]["probe_observations"][
        "queried_treated_address_count"
    ] == 17
    assert sources["observed_outcomes"]["probe_observations"][
        "bounded_permit_row_count"
    ] == 70
    assert sources["observed_outcomes"]["probe_observations"][
        "complete_tract_permit_universe_verified"
    ] is False
    assert sources["observed_outcomes"]["probe_observations"][
        "snapshot_raw_row_count"
    ] == 114896
    assert sources["observed_outcomes"]["probe_observations"][
        "spatially_admitted_permit_row_count"
    ] == 114816
    assert sources["observed_outcomes"]["probe_observations"][
        "spatially_unresolved_permit_row_count"
    ] == 72
    assert sources["observed_outcomes"]["probe_observations"][
        "tract_month_panel_row_count"
    ] == 33642
    assert sources["observed_outcomes"]["probe_observations"][
        "candidate_control_outcomes_materialized"
    ] is True
    assert sources["observed_outcomes"]["probe_observations"][
        "official_arcgis_externalapps_service_count"
    ] == 32
    assert sources["observed_outcomes"]["probe_observations"][
        "official_arcgis_building_permit_layer_discovered"
    ] is False
    assert sources["observed_outcomes"]["probe_observations"][
        "public_way_use_permits_rejected_as_building_outcome"
    ] is True
    network_source = sources["interference_network"]
    assert network_source["authority_status"] == "verified_official"
    assert network_source["derivation_status"] == (
        "deterministic_from_verified_official_geometry"
    )
    assert network_source["schema_probe_status"] == "pass"
    assert network_source["sample_validation_status"] == "pass"
    assert network_source["license_status"] == "pass"
    assert network_source["probe_observations"][
        "official_queen_edge_count"
    ] == 2636
    assert network_source["probe_observations"][
        "official_rook_edge_count"
    ] == 1889
    assert network_source["probe_observations"][
        "official_topology_quality_pass"
    ] is True
    assert network_source["probe_observations"][
        "official_cook_dupage_city_internal_network_ready"
    ] is True
    assert network_source["probe_observations"][
        "network_to_unit_time_ready"
    ] is True
    assert network_source["probe_observations"][
        "causal_estimation_ready"
    ] is False
    assert sources["time_varying_confounders"]["access_boundary"] == (
        "api_key_required"
    )
    assert "overlapping five-year estimates" in sources[
        "time_varying_confounders"
    ]["temporal_semantics"]
    assert sources["time_varying_confounders"]["fallback_probe_observations"][
        "release_id"
    ] == "acs2024_5yr"
    assert sources["time_varying_confounders"]["fallback_probe_observations"][
        "official_census_api_sample_still_required"
    ] is True
    assert sources["spatial_units"]["probe_observations"][
        "headed_browser_download_succeeded"
    ] is True
    assert sources["spatial_units"]["source_id"] == (
        "tiger_2020_illinois_tract_boundaries"
    )
    assert sources["spatial_units"]["metadata_probe_status"] == "pass"
    assert sources["spatial_units"]["license_status"] == "pass"
    assert sources["spatial_units"]["geography_coverage_status"] == "pass"
    assert sources["spatial_units"]["sample_validation_status"] == "pass"
    assert sources["spatial_units"]["probe_observations"][
        "official_catalog_identity_verified"
    ] is True
    assert sources["spatial_units"]["probe_observations"][
        "official_iso_metadata_verified"
    ] is True
    assert sources["spatial_units"]["probe_observations"][
        "official_iso_crs"
    ] == "EPSG:4269"
    assert sources["spatial_units"]["probe_observations"][
        "official_geometry_component_hashes_verified"
    ] is True
    assert sources["spatial_units"]["probe_observations"][
        "official_statewide_tract_count"
    ] == 3265
    assert sources["spatial_units"]["probe_observations"][
        "official_cook_tract_count"
    ] == 1332
    assert sources["spatial_units"]["probe_observations"][
        "fcc_2020_tract_geoid"
    ] == "17031671600"
    assert sources["spatial_units"]["probe_observations"][
        "secondary_geometry_not_official_tiger_admission"
    ] is True
    assert sources["spatial_units"]["probe_observations"][
        "city_census_tract_candidate_year"
    ] == 2000
    assert sources["spatial_units"]["probe_observations"][
        "city_census_tract_candidate_rejected_for_2020_panel"
    ] is True
    assert contract["provenance"]["selected_skills"] == [
        "browser-automation",
        "legistar-platform",
        "socrata-platform",
        "document-portal-platform",
        "census-acs",
        "us-tiger-boundaries",
        "arcgis-platform",
        "data-gov-catalog",
        "ckan-platform",
    ]
    assert contract["provenance"]["response_artifacts_saved"] is True
    assert contract["provenance"][
        "latest_probe_requests_bounded_to_metadata_and_samples"
    ] is False
    assert contract["provenance"][
        "latest_socrata_acquisition_is_bounded_complete_window"
    ] is True
    assert contract["provenance"][
        "latest_acquisition_bounded_to_two_official_documents"
    ] is True
    assert contract["provenance"]["bounded_official_document_bytes"] == 318554


def test_chicago_candidate_hash_binds_bounded_data_foundation_evidence():
    contract = build_chicago_longitudinal_panel_source_candidate()
    artifacts = contract["provenance"]["evidence_artifacts"]

    assert set(artifacts) == set(EVIDENCE_FILES)
    assert contract["provenance"]["bounded_response_artifact_count"] == 128
    audit = contract["provenance"]["data_foundation_audit"]
    assert audit["status"] == (
        "bounded_evidence_valid_partial_outcome_panel_materialized"
    )
    assert len(audit["report_digest"]) == 64
    assert audit["evidence_ref"].startswith(
        "artifact:benchmarks/gwm_bench_candidates/"
    )
    assert audit["all_checks_passed"] is True
    assert audit["panel_materialization_ready"] is False
    assert audit["network_to_unit_time_ready"] is True
    assert audit["observed_outcome_panel_materialized"] is True
    outcome_panel = contract["provenance"]["official_socrata_outcome_panel"]
    assert outcome_panel["raw_row_count"] == 114896
    assert outcome_panel["spatially_admitted_row_count"] == 114816
    assert outcome_panel["spatially_unresolved_row_count"] == 72
    assert outcome_panel["state_plane_recovered_row_count"] == 1542
    assert outcome_panel["exact_address_geocoder_recovered_row_count"] == 44
    assert outcome_panel["pin_parcel_recovered_row_count"] == 0
    assert outcome_panel["ohare_facility_context_row_count"] == 26
    assert outcome_panel["ohare_facility_point_used_as_permit_location"] is False
    assert outcome_panel["fuzzy_address_matches_admitted"] is False
    assert outcome_panel["unit_count"] == 801
    assert outcome_panel["cook_unit_count"] == 799
    assert outcome_panel["dupage_unit_count"] == 2
    assert outcome_panel["panel_row_count"] == 33642
    assert outcome_panel["verified_untreated_control_status_ready"] is False
    screening = contract["provenance"]["historical_candidate_screening"]
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
    assert screening["expanded_preregistered_event_count"] == 23
    assert screening["expanded_zoning_map_ready_count"] == 22
    assert screening["expanded_point_address_ready_count"] == 19
    assert screening["expanded_tract_crosswalk_ready_count"] == 19
    assert screening["expanded_current_parcel_crosswalk_ready_count"] == 19
    assert screening["expanded_joint_spatial_crosswalk_ready_count"] == 17
    assert screening["bounded_treated_address_outcome_count"] == 17
    assert screening["bounded_permit_row_count"] == 70
    assert screening["bounded_post_publication_permit_row_count"] == 18
    assert screening["complete_tract_permit_universe_ready"] is False
    assert screening["untreated_control_outcomes_ready"] is False
    assert screening["expanded_missing_zoning_map_records"] == [
        "O2024-0013362"
    ]
    assert screening["expanded_point_polygon_mismatch_records"] == [
        "O2024-0012332"
    ]
    assert screening["expanded_cohort_crosswalk_complete"] is False
    assert screening["historical_candidate_tract_geoids"] == [
        "17031243400",
        "17031300900",
        "17031830600",
    ]
    assert screening["machine_treatment_geometries_ready"] is False
    assert screening["effective_onsets_ready"] is False
    assert screening["cohort_panel_ready"] is False
    assert screening["causal_estimation_ready"] is False
    for filename, artifact in artifacts.items():
        path = ROOT / artifact["path"]
        payload = path.read_bytes()
        assert str(path.relative_to(ROOT)) == artifact["path"]
        assert len(payload) == artifact["bytes"]
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]


def test_chicago_crosswalk_opens_only_verified_network_gate():
    contract = build_chicago_longitudinal_panel_source_candidate()
    crosswalks = contract["crosswalk_evidence"]

    treatment = crosswalks["treatment_to_unit"]
    assert treatment["passed"] is False
    assert treatment["evidence_refs"]
    assert treatment["details"]["official_address_point_verified"] is True
    assert treatment["details"]["point_to_2020_census_tract_verified"] is True
    assert treatment["details"][
        "historical_candidate_point_addresses_verified"
    ] is True
    assert treatment["details"][
        "historical_candidate_pins_verified"
    ] is True
    assert treatment["details"][
        "historical_candidate_point_to_tract_crosswalks_verified"
    ] is True
    assert treatment["details"][
        "historical_current_zoning_map_polygons_verified"
    ] is True
    assert treatment["details"][
        "historical_machine_legal_parcel_polygons_verified"
    ] is False
    assert treatment["details"]["expanded_preregistered_event_count"] == 23
    assert treatment["details"]["expanded_zoning_map_ready_count"] == 22
    assert treatment["details"]["expanded_point_address_ready_count"] == 19
    assert treatment["details"]["expanded_tract_crosswalk_ready_count"] == 19
    assert treatment["details"][
        "expanded_current_parcel_crosswalk_ready_count"
    ] == 19
    assert treatment["details"][
        "expanded_joint_spatial_crosswalk_ready_count"
    ] == 17
    assert treatment["details"]["expanded_cohort_crosswalk_complete"] is False
    assert treatment["details"]["enacted_zoning_transition_verified"] is True
    assert treatment["details"]["legal_treatment_boundary_verified"] is True
    assert treatment["details"]["affected_treatment_polygon_verified"] is False
    assert treatment["details"]["machine_treatment_polygon_verified"] is False
    assert treatment["details"][
        "official_cook_county_parcel_metadata_verified"
    ] is True
    assert treatment["details"][
        "official_target_pin_geometry_sample_verified"
    ] is False

    outcomes = crosswalks["outcome_to_unit"]
    assert outcomes["passed"] is False
    assert outcomes["details"]["official_catalog_metadata_verified"] is True
    assert outcomes["details"][
        "official_historical_schema_semantics_verified"
    ] is True
    assert outcomes["details"][
        "official_issue_date_fallback_semantics_verified"
    ] is True
    assert outcomes["details"]["current_address_level_schema_verified"] is True
    assert outcomes["details"]["row_sample_verified"] is True
    assert outcomes["details"]["bounded_permit_row_count"] == 70
    assert outcomes["details"]["bounded_snapshot_raw_row_count"] == 114896
    assert outcomes["details"]["tract_month_panel_row_count"] == 33642
    assert outcomes["details"]["spatially_admitted_permit_row_count"] == 114816
    assert outcomes["details"]["spatially_unresolved_permit_row_count"] == 72
    assert outcomes["details"]["state_plane_recovered_permit_row_count"] == 1542
    assert outcomes["details"][
        "exact_address_geocoder_recovered_permit_row_count"
    ] == 44
    assert outcomes["details"]["pin_parcel_recovered_permit_row_count"] == 0
    assert outcomes["details"]["ohare_facility_context_row_count"] == 26
    assert outcomes["details"][
        "ohare_facility_point_used_as_permit_location"
    ] is False
    assert outcomes["details"]["fuzzy_address_geocoder_matches_admitted"] is False
    assert outcomes["details"]["spatial_missingness_assumed_random"] is False
    assert outcomes["details"]["candidate_control_outcomes_materialized"] is True
    assert outcomes["details"][
        "bounded_treated_address_to_tract_crosswalk_count"
    ] == 17
    assert outcomes["details"][
        "complete_tract_permit_universe_verified"
    ] is False
    assert outcomes["details"]["untreated_control_outcomes_verified"] is False

    network = crosswalks["network_to_unit_time"]
    assert network["passed"] is True
    assert network["details"]["secondary_full_cook_geometry_verified"] is True
    assert network["details"][
        "official_tiger2020_catalog_identity_verified"
    ] is True
    assert network["details"]["official_tiger2020_iso_metadata_verified"] is True
    assert network["details"]["official_tiger2020_license_verified"] is True
    assert network["details"]["official_tiger2020_declared_crs"] == "EPSG:4269"
    assert network["details"][
        "official_tiger2020_component_hashes_verified"
    ] is True
    assert network["details"]["official_statewide_tract_count"] == 3265
    assert network["details"]["official_chicago_city_tract_count"] == 801
    assert network["details"]["official_chicago_cook_tract_count"] == 799
    assert network["details"]["official_chicago_dupage_tract_count"] == 2
    assert network["details"]["target_distinct_tract_count"] == 17
    assert network["details"]["secondary_topology_quality_pass"] is False
    assert network["details"]["official_tiger2020_geometry_verified"] is True
    assert network["details"]["official_adjacency_constructed"] is True
    assert network["details"]["official_queen_edge_count"] == 2636
    assert network["details"]["official_rook_edge_count"] == 1889
    assert network["details"]["official_topology_quality_pass"] is True
    assert network["details"]["target_tracts_with_zero_rook_neighbors"] == []
    assert network["details"][
        "official_cook_dupage_city_internal_network_ready"
    ] is True
    assert network["details"]["outside_city_interference_ready"] is False

    future = crosswalks["no_future_information_leakage"]
    assert future["passed"] is False
    assert future["details"]["historical_network_vintage_verified"] is True
    assert future["details"]["network_future_geometry_change_excluded"] is True
    assert future["details"]["full_panel_information_leakage_verified"] is False
    assert future["details"]["outcome_current_status_fields_excluded"] is True
    assert future["details"]["outcome_panel_materialized"] is True

    confounders = crosswalks["confounder_to_unit"]
    assert confounders["passed"] is False
    assert confounders["details"]["secondary_estimate_moe_sample_verified"] is True
    assert confounders["details"]["official_acs_sample_verified"] is False
    assert confounders["details"]["official_tiger_geometry_verified"] is True

    unit_time = crosswalks["unit_time_alignment"]
    assert unit_time["passed"] is False
    assert unit_time["evidence_refs"]
    assert unit_time["details"]["complete_post_treatment_months_available"] == 0
    assert unit_time["details"]["reason"] == (
        "no_complete_monthly_post_treatment_period"
    )


def test_source_contract_only_seeds_closed_spatiotemporal_design_gates():
    blocked_seed = seed_spatiotemporal_gate_evidence_from_panel_sources(
        build_chicago_longitudinal_panel_source_candidate()
    )
    assert set(blocked_seed) == set(
        (*LONGITUDINAL_DESIGN_GATES, *LONGITUDINAL_ESTIMATION_GATES)
    )
    assert all(gate["passed"] is False for gate in blocked_seed.values())
    assert {
        gate["details"]["reason"] for gate in blocked_seed.values()
    } == {"source_panel_not_materialization_ready"}

    materializable_seed = seed_spatiotemporal_gate_evidence_from_panel_sources(
        _contract()
    )
    assert all(gate["passed"] is False for gate in materializable_seed.values())
    assert {
        gate["details"]["reason"] for gate in materializable_seed.values()
    } == {"source_panel_ready_but_materialization_and_design_checks_not_run"}


def test_contract_hash_tampering_is_detected():
    contract = _contract()
    contract["candidate"]["target_cadence"] = "weekly"
    validation = validate_longitudinal_panel_source_contract(contract)

    assert validation["valid"] is False
    assert "contract_digest_mismatch" in validation["errors"]


def test_generated_chicago_candidate_matches_checked_artifact():
    assert DEFAULT_OUTPUT.is_file()
    checked = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    assert checked == build_chicago_longitudinal_panel_source_candidate()
    assert Path(DEFAULT_OUTPUT).name == "source_candidate_contract.json"
