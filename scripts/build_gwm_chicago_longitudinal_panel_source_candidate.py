#!/usr/bin/env python3
"""Build the bounded Chicago longitudinal panel source candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel.longitudinal_panel_sources import (
    LONGITUDINAL_PANEL_CROSSWALK_GATES,
    build_longitudinal_panel_source_contract,
    validate_longitudinal_panel_source_contract,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel"
    / "source_candidate_contract.json"
)
EVIDENCE_DIR = DEFAULT_OUTPUT.parent / "evidence"
BUILDING_RECORD_HTML_FILES = (
    "chicago_building_records_2024_cohort_html/agreement.html",
    "chicago_building_records_2024_cohort_html/O2024_0008450.html",
    "chicago_building_records_2024_cohort_html/O2024_0008454.html",
    "chicago_building_records_2024_cohort_html/O2024_0008459.html",
    "chicago_building_records_2024_cohort_html/O2024_0008868.html",
    "chicago_building_records_2024_cohort_html/O2024_0008869.html",
    "chicago_building_records_2024_cohort_html/O2024_0008974.html",
    "chicago_building_records_2024_cohort_html/O2024_0009009.html",
    "chicago_building_records_2024_cohort_html/O2024_0010948.html",
    "chicago_building_records_2024_cohort_html/O2024_0010950.html",
    "chicago_building_records_2024_cohort_html/O2024_0011132.html",
    "chicago_building_records_2024_cohort_html/O2024_0011139.html",
    "chicago_building_records_2024_cohort_html/O2024_0011150.html",
    "chicago_building_records_2024_cohort_html/O2024_0012247.html",
    "chicago_building_records_2024_cohort_html/O2024_0012334.html",
    "chicago_building_records_2024_cohort_html/O2024_0012506.html",
    "chicago_building_records_2024_cohort_html/O2024_0012520.html",
    "chicago_building_records_2024_cohort_html/O2024_0012532.html",
)
SOCRATA_OUTCOME_EVIDENCE_FILES = (
    "chicago_socrata_building_permits_metadata_browser.json",
    "chicago_socrata_building_permits_metadata_browser.json.capture.json",
    "chicago_data_portal_terms_of_use.html",
    "chicago_data_portal_terms_of_use.html.capture.json",
    "chicago_socrata_building_permits_current_sample_browser.json",
    "chicago_socrata_building_permits_current_sample_browser.json.capture.json",
    "chicago_socrata_building_permits_race_crosscheck_browser.json",
    "chicago_socrata_building_permits_race_crosscheck_browser.json.capture.json",
    "chicago_socrata_building_permits_2023_2026_tract_summary_browser.json",
    "chicago_socrata_building_permits_2023_2026_tract_summary_browser.json.capture.json",
    *tuple(
        filename
        for part_index in range(5)
        for filename in (
            f"chicago_socrata_building_permits_2023_2026_raw/part-{part_index:05d}.json",
            f"chicago_socrata_building_permits_2023_2026_raw/part-{part_index:05d}.json.capture.json",
        )
    ),
    "tiger2020_illinois_place/tl_2020_17_place.cpg",
    "tiger2020_illinois_place/tl_2020_17_place.dbf",
    "tiger2020_illinois_place/tl_2020_17_place.prj",
    "tiger2020_illinois_place/tl_2020_17_place.shp",
    "tiger2020_illinois_place/tl_2020_17_place.shp.ea.iso.xml",
    "tiger2020_illinois_place/tl_2020_17_place.shp.iso.xml",
    "tiger2020_illinois_place/tl_2020_17_place.shx",
    "chicago_building_permits_2023_2026_tract_month_panel.json",
    "chicago_socrata_building_permits_2023_2026_missing_coordinates_address_browser.json",
    "chicago_socrata_building_permits_2023_2026_missing_coordinates_address_browser.json.capture.json",
    "chicago_building_permits_unresolved_address_geocoder_request.json",
    "chicago_building_permits_spatial_missingness_diagnostic.json",
    "chicago_building_permits_unresolved_address_geocoder_response.json",
    "chicago_building_permits_unresolved_pin_parcel_response.json",
    "chicago_building_permits_unresolved_pin_parcel_response.headers",
    "chicago_official_airports_layer31_metadata.json",
    "chicago_official_airports_layer31_all_features.json",
    "chicago_building_permits_remaining_spatial_adjudication.json",
)

EVIDENCE_FILES = (
    "datagov_v4_chicago_building_permits_search.json",
    "datagov_chicago_building_permits_harvest_raw.json",
    "chicago_addresspoints_6716_s_bishop.json",
    "fcc_census_block_6716_s_bishop.json",
    "chicago_current_zoning_6716_s_bishop.json",
    "chicago_current_zoning_case_23063.json",
    "census_reporter_acs2024_tract_17031671600.json",
    "census_reporter_tiger2024_tract_17031671600.json",
    "census_reporter_tiger2024_cook_county_tracts.json",
    "chicago_provisional_tract_adjacency.json",
    "chicago_official_tiger2020_tract_adjacency.json",
    "chicago_official_tiger2020_city_tract_adjacency.json",
    "tiger2020_illinois_tract/tl_2020_17_tract.cpg",
    "tiger2020_illinois_tract/tl_2020_17_tract.dbf",
    "tiger2020_illinois_tract/tl_2020_17_tract.prj",
    "tiger2020_illinois_tract/tl_2020_17_tract.shp",
    "tiger2020_illinois_tract/tl_2020_17_tract.shp.ea.iso.xml",
    "tiger2020_illinois_tract/tl_2020_17_tract.shp.iso.xml",
    "tiger2020_illinois_tract/tl_2020_17_tract.shx",
    "datagov_v4_tiger2020_illinois_tract_search.json",
    "datagov_tiger2020_illinois_harvest_raw.xml",
    "chicago_elms_matter_O2026_0024863.json",
    "chicago_elms_O2026_0024863_final_ordinance.pdf",
    "chicago_elms_O2026_0024863_final_ordinance_ocr.txt",
    "chicago_elms_O2026_0024863_final_narrative_and_plans.pdf",
    "chicago_elms_O2026_0024863_final_narrative_and_plans_ocr.txt",
    "datagov_v4_cook_county_parcel_2021_search.json",
    "cook_county_parcel_2021_arcgis_item.json",
    "cook_county_parcel_2021_hub_metadata.json",
    "chicago_dev_portal_github_repository.json",
    "chicago_official_building_permits_changes_2019_07_09.md",
    "chicago_official_building_permits_issue_date_2017_11_20.md",
    "chicago_official_building_permits_contact_columns_2019_07_16.md",
    "chicago_elms_pre2025_zoning_with_exhibits.json",
    "chicago_elms_O2024_0012247_race_detail.json",
    "chicago_elms_O2024_0012532_bosworth_detail.json",
    "chicago_elms_O2024_0012334_troy_detail.json",
    "chicago_elms_historical_candidate_attachment_preflight.json",
    "chicago_elms_O2024_0012247_final_ordinance.pdf",
    "chicago_elms_O2024_0012247_final_ordinance_ocr.txt",
    "chicago_elms_O2024_0012247_final_narrative_and_plans.pdf",
    "chicago_elms_O2024_0012247_final_narrative_and_plans_ocr.txt",
    "chicago_elms_O2024_0012532_final_ordinance.pdf",
    "chicago_elms_O2024_0012532_final_ordinance_ocr.txt",
    "chicago_elms_O2024_0012532_final_narrative_and_plans.pdf",
    "chicago_elms_O2024_0012532_final_narrative_and_plans_ocr.txt",
    "chicago_elms_O2024_0012334_final_ordinance.pdf",
    "chicago_elms_O2024_0012334_final_ordinance_ocr.txt",
    "chicago_elms_O2024_0012334_final_narrative_and_plans.pdf",
    "chicago_elms_O2024_0012334_final_narrative_and_plans_ocr.txt",
    "chicago_addresspoints_O2024_0012247_race.json",
    "chicago_addresspoints_O2024_0012532_bosworth.json",
    "chicago_addresspoints_O2024_0012334_troy.json",
    "fcc_census_block_O2024_0012247_race.json",
    "fcc_census_block_O2024_0012532_bosworth.json",
    "fcc_census_block_O2024_0012334_troy.json",
    "chicago_current_zoning_O2024_0012247_race.json",
    "chicago_current_zoning_O2024_0012532_bosworth.json",
    "chicago_current_zoning_O2024_0012334_troy.json",
    "chicago_elms_2023_2024_zoning_cohort_raw.json",
    "historical_cohort_preregistration.json",
    "historical_cohort_spatial_crosswalk.json",
    "chicago_official_operational_mapserver_metadata.json",
    "chicago_official_arcgis_externalapps_directory.json",
    "chicago_official_permit_mapserver_metadata.json",
    "chicago_official_permit_map_layer12_metadata.json",
    "chicago_official_census_tract_layer84_metadata.json",
    "chicago_official_census_tract_layer84_count_probe.json",
    "chicago_official_census_tract_layer84_year_probe.json",
    "chicago_building_records_2024_cohort.json",
    *BUILDING_RECORD_HTML_FILES,
    *SOCRATA_OUTCOME_EVIDENCE_FILES,
    "historical_event_crosswalk.json",
    "data_foundation_audit.json",
)


def build_chicago_longitudinal_panel_source_candidate() -> dict[str, Any]:
    """Return the probe-bounded candidate without fetching source assets."""

    evidence_artifacts = _evidence_artifact_manifest()
    data_foundation_audit = json.loads(
        (EVIDENCE_DIR / "data_foundation_audit.json").read_text(encoding="utf-8")
    )
    building_records = json.loads(
        (EVIDENCE_DIR / "chicago_building_records_2024_cohort.json").read_text(
            encoding="utf-8"
        )
    )
    building_records_source = building_records["source"]
    building_records_summary = building_records["summary"]
    building_records_readiness = building_records["readiness"]
    permit_panel = json.loads(
        (
            EVIDENCE_DIR
            / "chicago_building_permits_2023_2026_tract_month_panel.json"
        ).read_text(encoding="utf-8")
    )
    permit_panel_query = permit_panel["query_contract"]
    permit_panel_summary = permit_panel["panel_summary"]
    permit_assignment = permit_panel["assignment_diagnostics"]
    permit_panel_readiness = permit_panel["readiness"]
    provisional_adjacency = json.loads(
        (EVIDENCE_DIR / "chicago_provisional_tract_adjacency.json").read_text(
            encoding="utf-8"
        )
    )
    provisional_graph = provisional_adjacency["graph_summary"]
    provisional_quality = provisional_adjacency[
        "topology_quality_diagnostics"
    ]
    provisional_target = provisional_adjacency["target_cohort"]
    provisional_readiness = provisional_adjacency["readiness"]
    official_adjacency = json.loads(
        (
            EVIDENCE_DIR
            / "chicago_official_tiger2020_tract_adjacency.json"
        ).read_text(encoding="utf-8")
    )
    official_geometry = official_adjacency["geometry_validation"]
    official_graph = official_adjacency["graph_summary"]
    official_quality = official_adjacency["topology_quality_diagnostics"]
    official_target = official_adjacency["target_cohort"]
    official_readiness = official_adjacency["readiness"]
    city_adjacency = json.loads(
        (
            EVIDENCE_DIR
            / "chicago_official_tiger2020_city_tract_adjacency.json"
        ).read_text(encoding="utf-8")
    )
    city_units = city_adjacency["unit_contract"]
    city_graph = city_adjacency["graph_summary"]
    city_quality = city_adjacency["topology_quality_diagnostics"]
    city_target = city_adjacency["target_cohort"]
    city_readiness = city_adjacency["readiness"]
    remaining_spatial_adjudication = json.loads(
        (
            EVIDENCE_DIR
            / "chicago_building_permits_remaining_spatial_adjudication.json"
        ).read_text(encoding="utf-8")
    )
    remaining_pin = remaining_spatial_adjudication["pin_parcel_adjudication"]
    remaining_facility = remaining_spatial_adjudication["facility_context"]
    remaining_readiness = remaining_spatial_adjudication["readiness"]

    def artifact_ref(filename: str) -> str:
        artifact = evidence_artifacts[filename]
        return f"artifact:{artifact['path']}#sha256:{artifact['sha256']}"

    treatment_detail_url = (
        "https://api.chicityclerkelms.chicago.gov/matter/"
        "86390664-2D38-F111-88B3-001DD8033B18"
    )
    treatment_ordinance_url = (
        "https://occprodstoragev1.blob.core.usgovcloudapi.net/"
        "matterattachmentspublic/06f59372-b713-4371-a145-92028931a3bd.pdf"
    )
    treatment_plan_url = (
        "https://occprodstoragev1.blob.core.usgovcloudapi.net/"
        "matterattachmentspublic/8a22ded0-47d3-40ca-bb35-c2d5961095fa.pdf"
    )
    cook_county_parcel_url = (
        "https://gis.cookcountyil.gov/hosting/rest/services/Hosted/"
        "Parcel2021_enhancedAll/FeatureServer/0"
    )
    sources = [
        {
            "source_id": "chicago_elms_zoning_reclassification",
            "role": "treatment_events",
            "publisher": "Office of the City Clerk, City of Chicago",
            "canonical_url": treatment_detail_url,
            "platform": "chicago_elms",
            "authority_status": "verified_official",
            "access_boundary": "none",
            "metadata_probe_status": "pass",
            "schema_probe_status": "pass",
            "license_status": "review",
            "time_coverage_status": "review",
            "geography_coverage_status": "review",
            "sample_validation_status": "pass",
            "stable_id_fields": ["matterId", "recordNumber"],
            "time_fields": [
                "introductionDate",
                "finalActionDate",
                "actions.actionDate",
                "lastPublicationDate",
            ],
            "geometry_fields": [
                "title_address_text",
                "attachments.final_ordinance_legal_description",
                "attachments.final_narrative_and_plans",
                "official_chicago_point_address",
                "fcc_census_block_crosswalk",
                "cook_county_parcel_pin_candidate",
                "current_zoning_polygon_diagnostic",
            ],
            "temporal_semantics": (
                "finalActionDate is the observed legislative passage date; the "
                "ordinance takes effect after passage and due publication, but the "
                "legal semantics of eLMS lastPublicationDate and exact treatment "
                "onset remain independently unverified"
            ),
            "evidence_refs": [
                "https://api.chicityclerkelms.chicago.gov/swagger.json",
                treatment_detail_url,
                treatment_ordinance_url,
                treatment_plan_url,
                cook_county_parcel_url,
                (
                    "https://www.arcgis.com/home/item.html?id="
                    "3d4c78a939484610b554b64d1a3e9120"
                ),
                (
                    "https://gisapps.chicago.gov/arcgis/rest/services/"
                    "AddressPoints/GeocodeServer"
                ),
                "https://geo.fcc.gov/api/census/block/find",
                (
                    "https://services7.arcgis.com/A03QrhyHnDaUmK0W/arcgis/"
                    "rest/services/Zoning/FeatureServer/0"
                ),
                artifact_ref("chicago_addresspoints_6716_s_bishop.json"),
                artifact_ref("fcc_census_block_6716_s_bishop.json"),
                artifact_ref("chicago_current_zoning_6716_s_bishop.json"),
                artifact_ref("chicago_current_zoning_case_23063.json"),
                artifact_ref("chicago_elms_matter_O2026_0024863.json"),
                artifact_ref(
                    "chicago_elms_O2026_0024863_final_ordinance.pdf"
                ),
                artifact_ref(
                    "chicago_elms_O2026_0024863_final_ordinance_ocr.txt"
                ),
                artifact_ref(
                    "chicago_elms_O2026_0024863_final_narrative_and_plans.pdf"
                ),
                artifact_ref(
                    "chicago_elms_O2026_0024863_final_narrative_and_plans_ocr.txt"
                ),
                artifact_ref("datagov_v4_cook_county_parcel_2021_search.json"),
                artifact_ref("cook_county_parcel_2021_arcgis_item.json"),
                artifact_ref("cook_county_parcel_2021_hub_metadata.json"),
            ],
            "probe_observations": {
                "matter_id": "86390664-2D38-F111-88B3-001DD8033B18",
                "record_number": "O2026-0024863",
                "matter_category": "ZONING RECLASSIFICATIONS",
                "status": "90-Final",
                "sub_status": "Passed",
                "introduction_date": "2026-04-15T15:00:00+00:00",
                "final_action_date": "2026-07-15T15:00:00+00:00",
                "elms_last_publication_date": "2026-07-17T14:25:18+00:00",
                "title": (
                    "Zoning Reclassification Map No. 16-G at 6716 S Bishop St "
                    "- App No. 23063T1"
                ),
                "final_narrative_and_plans_bytes": 291862,
                "final_ordinance_bytes": 26692,
                "attachment_downloaded_to_project": True,
                "attachment_probe_method": (
                    "HEAD_then_bounded_project_download_and_local_vision_ocr"
                ),
                "latest_attachment_bytes_transferred": 318554,
                "known_total_attachment_bytes_transferred": 610416,
                "enacted_from_zoning": "RS-3",
                "enacted_to_zoning": "RM-4.5",
                "ordinance_effective_rule": "after passage and due publication",
                "elms_last_publication_field_legal_semantics_verified": False,
                "effective_date_verified": False,
                "latest_official_permit_catalog_date": "2026-07-21",
                "complete_monthly_post_treatment_periods": 0,
                "temporally_viable_for_effect_estimation": False,
                "candidate_temporal_role": (
                    "crosswalk_fixture_not_effect_estimation_pilot"
                ),
                "legal_treatment_boundary_verified": True,
                "legal_boundary_north_offset_from_marquette_feet": 166,
                "legal_boundary_south_offset_from_marquette_feet": 191,
                "legal_boundary_depth_feet": 25,
                "legal_boundary_east": "South Bishop Street",
                "legal_boundary_west": (
                    "alley next west of and parallel to South Bishop Street"
                ),
                "narrative_lot_area_square_feet": 3115,
                "treatment_polygon_verified": False,
                "machine_treatment_polygon_verified": False,
                "official_point_address_verified": True,
                "official_point_address_score": 100,
                "official_point_address_type": "PointAddress",
                "official_point_address_pin": "2020302029",
                "official_point_address_ward": 16,
                "official_point_address_community": "WEST ENGLEWOOD",
                "official_point_address_epsg": 3435,
                "official_point_address_x": 1167755.5154296386,
                "official_point_address_y": 1860103.2615483797,
                "official_point_address_longitude": -87.66061727108206,
                "official_point_address_latitude": 41.77166529892371,
                "fcc_2020_census_block_fips": "170316716001013",
                "fcc_2020_census_tract_geoid": "17031671600",
                "point_to_2020_tract_verified": True,
                "current_zoning_class_at_point": "RS-3",
                "current_zoning_object_id": 1661018,
                "current_zoning_case_number": None,
                "current_zoning_clerk_document_number": None,
                "current_zoning_case_23063_feature_count": 0,
                "current_zoning_is_treatment_polygon": False,
                "official_cook_county_parcel_metadata_verified": True,
                "official_cook_county_parcel_dataset_id": "77tz-riq7",
                "official_cook_county_parcel_arcgis_item_id": (
                    "34021b4f3b834a69bf737e6c3344888e"
                ),
                "official_cook_county_parcel_geometry_type": (
                    "esriGeometryPolygon"
                ),
                "official_cook_county_parcel_license_declared": True,
                "official_cook_county_target_pin_sample_verified": False,
                "official_cook_county_target_pin_query_status": "timeout",
            },
        },
        {
            "source_id": "chicago_official_building_permit_outcomes",
            "role": "observed_outcomes",
            "publisher": "City of Chicago Department of Buildings",
            "canonical_url": "https://data.cityofchicago.org/d/ydr8-5enu",
            "platform": "socrata_browser_cdp_and_official_html_application",
            "authority_status": "verified_official",
            "access_boundary": "browser_or_waf",
            "metadata_probe_status": "pass",
            "schema_probe_status": "pass",
            "license_status": "pass",
            "time_coverage_status": "pass",
            "geography_coverage_status": "review",
            "sample_validation_status": "pass",
            "stable_id_fields": ["id", "permit_"],
            "time_fields": ["application_start_date", "issue_date"],
            "geometry_fields": [
                "census_tract",
                "latitude",
                "longitude",
                "point_in_official_tiger2020_tract_crosswalk",
            ],
            "temporal_semantics": (
                "ISSUE_DATE is an administrative permit event and does not prove "
                "construction start, completion, or realized work. The frozen snapshot "
                "uses complete months from 2023-01-01 through 2026-06-30; current status "
                "fields are excluded to reduce future-state leakage."
            ),
            "evidence_refs": [
                "https://data.cityofchicago.org/d/ydr8-5enu",
                (
                    "https://api.gsa.gov/technology/datagov/v4/search?"
                    "q=Chicago%20Building%20Permits&page_size=10&api_key=DEMO_KEY"
                ),
                (
                    "https://catalog.data.gov/harvest_record/"
                    "84c65b32-b1c2-401c-9e8e-ca1d07c3811f/raw"
                ),
                artifact_ref("datagov_v4_chicago_building_permits_search.json"),
                artifact_ref("datagov_chicago_building_permits_harvest_raw.json"),
                (
                    "https://github.com/Chicago/dev.cityofchicago.org/blob/"
                    "431215dd236112dfe2e644d327637dd7afb00c3b/_posts/"
                    "2019-07-09-building-permits-changes.md"
                ),
                (
                    "https://github.com/Chicago/dev.cityofchicago.org/blob/"
                    "431215dd236112dfe2e644d327637dd7afb00c3b/_posts/"
                    "2017-11-20-building-permits-issue-date.md"
                ),
                (
                    "https://github.com/Chicago/dev.cityofchicago.org/blob/"
                    "431215dd236112dfe2e644d327637dd7afb00c3b/_posts/"
                    "2019-07-16-building-permits-contact-columns.md"
                ),
                artifact_ref("chicago_dev_portal_github_repository.json"),
                artifact_ref(
                    "chicago_official_building_permits_changes_2019_07_09.md"
                ),
                artifact_ref(
                    "chicago_official_building_permits_issue_date_2017_11_20.md"
                ),
                artifact_ref(
                    "chicago_official_building_permits_contact_columns_2019_07_16.md"
                ),
                artifact_ref(
                    "chicago_official_arcgis_externalapps_directory.json"
                ),
                artifact_ref("chicago_official_permit_mapserver_metadata.json"),
                artifact_ref("chicago_official_permit_map_layer12_metadata.json"),
                "https://webapps1.chicago.gov/buildingrecords/",
                artifact_ref("chicago_building_records_2024_cohort.json"),
                *[
                    artifact_ref(filename)
                    for filename in BUILDING_RECORD_HTML_FILES
                ],
                *[
                    artifact_ref(filename)
                    for filename in SOCRATA_OUTCOME_EVIDENCE_FILES
                ],
                "probe:curl_http_403_then_headed_browser_cdp_capture:2026-07-24",
            ],
            "probe_observations": {
                "metadata_http_status": 403,
                "bounded_sample_http_status": 403,
                "socrata_odata_http_status": 403,
                "socrata_v3_bounded_query_http_status": 403,
                "socrata_global_catalog_http_status": 403,
                "datagov_v4_catalog_http_status": 200,
                "datagov_catalog_title": "Building Permits",
                "datagov_catalog_organization": "City of Chicago",
                "datagov_catalog_organization_type": "City Government",
                "datagov_catalog_access_level": "public",
                "datagov_catalog_coverage_start_year": 2006,
                "datagov_catalog_coverage_end": "present",
                "datagov_catalog_modified": "2026-07-21",
                "datagov_catalog_last_harvested": (
                    "2026-07-21T22:26:46.219904"
                ),
                "datagov_catalog_distribution_media_types": [
                    "application/json",
                    "application/xml",
                    "text/csv",
                    "application/vnd.google-earth.kml+xml",
                    "application/vnd.google-earth.kmz",
                    "application/geo+json",
                ],
                "datagov_catalog_license_declared": False,
                "official_chicago_developer_repository_verified": True,
                "official_historical_schema_semantics_verified": True,
                "official_historical_schema_documented_at": (
                    "2019-07-09T16:00:00-05:00"
                ),
                "documented_candidate_time_fields": [
                    "APPLICATION_START_DATE",
                    "ISSUE_DATE",
                    "PROCESSING_TIME",
                ],
                "documented_candidate_spatial_fields": [
                    "COMMUNITY_AREA",
                    "CENSUS_TRACT",
                    "WARD",
                    "XCOORDINATE",
                    "YCOORDINATE",
                ],
                "documented_candidate_cost_field": "REPORTED_COST",
                "official_issue_date_fallback_semantics_verified": True,
                "issue_date_fallback_only_when_primary_blank": True,
                "historical_issue_date_missing_share_approximate": 0.05,
                "issue_date_is_not_construction_start": True,
                "official_contact_field_removal_semantics_verified": True,
                "bulk_contact_fields_intentionally_removed_for_privacy": True,
                "building_records_agreement_http_status": (
                    building_records_source["agreement_http_status"]
                ),
                "building_records_home_http_status": (
                    building_records_source["home_http_status"]
                ),
                "building_records_access_mode": building_records_source[
                    "access_mode"
                ],
                "current_address_level_permit_columns": (
                    building_records_source["current_permit_columns"]
                ),
                "row_schema_verified": building_records_readiness[
                    "official_current_address_level_schema_verified"
                ],
                "row_sample_verified": building_records_readiness[
                    "official_bounded_address_level_rows_verified"
                ],
                "queried_treated_address_count": building_records_summary[
                    "exact_input_address_count"
                ],
                "address_history_with_permits_count": (
                    building_records_summary[
                        "address_history_with_permits_count"
                    ]
                ),
                "zero_permit_address_history_count": building_records_summary[
                    "zero_permit_address_history_count"
                ],
                "bounded_permit_row_count": building_records_summary[
                    "permit_row_count"
                ],
                "bounded_post_publication_permit_row_count": (
                    building_records_summary[
                        "post_publication_permit_row_count"
                    ]
                ),
                "socrata_dataset_id": "ydr8-5enu",
                "socrata_current_metadata_row_count": 842033,
                "socrata_current_schema_verified": True,
                "socrata_license_id": "SEE_TERMS_OF_USE",
                "official_terms_of_use_verified": True,
                "derivative_disclaimer_required": True,
                "snapshot_start_inclusive": "2023-01-01",
                "snapshot_end_exclusive": "2026-07-01",
                "snapshot_complete_month_count": 42,
                "snapshot_raw_row_count": permit_panel_query["row_count"],
                "snapshot_part_counts": permit_panel_query["part_counts"],
                "socrata_bulk_row_schema_verified": True,
                "official_row_snapshot_complete": True,
                "official_chicago_2020_tract_count": permit_panel_summary[
                    "unit_count"
                ],
                "spatially_admitted_permit_row_count": permit_assignment[
                    "admitted_row_count"
                ],
                "spatial_assignment_admitted_share": permit_assignment[
                    "admitted_share"
                ],
                "spatially_unresolved_permit_row_count": permit_assignment[
                    "unresolved_row_count"
                ],
                "outside_chicago_permit_row_count": permit_assignment[
                    "outside_city_row_count"
                ],
                "point_source_conflict_row_count": permit_assignment[
                    "direct_point_conflict_count"
                ],
                "tract_month_panel_row_count": permit_panel_summary[
                    "panel_row_count"
                ],
                "tract_month_panel_permit_count": permit_panel_summary[
                    "permit_count"
                ],
                "candidate_control_tract_count": permit_panel_summary[
                    "candidate_control_tract_count"
                ],
                "candidate_control_outcomes_materialized": True,
                "complete_spatial_assignment_ready": permit_panel_readiness[
                    "complete_spatial_assignment_ready"
                ],
                "complete_tract_permit_universe_verified": False,
                "untreated_control_outcomes_verified": False,
                "tract_month_outcome_panel_materialized": True,
                "tract_month_outcome_panel_ready": False,
                "full_dataset_export_requested": False,
                "official_arcgis_externalapps_service_count": 32,
                "official_arcgis_permit_named_services": [
                    "ExternalApps/Permit_Map"
                ],
                "official_arcgis_building_permit_layer_discovered": False,
                "public_way_use_permit_layer_discovered": True,
                "public_way_use_permits_rejected_as_building_outcome": True,
            },
        },
        {
            "source_id": "census_acs5_2024_cook_tract_covariates",
            "role": "time_varying_confounders",
            "publisher": "United States Census Bureau",
            "canonical_url": "https://api.census.gov/data/2024/acs/acs5",
            "platform": "census_data_api",
            "authority_status": "verified_official",
            "access_boundary": "api_key_required",
            "metadata_probe_status": "blocked",
            "schema_probe_status": "review",
            "license_status": "pass",
            "time_coverage_status": "pass",
            "geography_coverage_status": "review",
            "sample_validation_status": "review",
            "stable_id_fields": ["state", "county", "tract"],
            "time_fields": ["acs_vintage"],
            "geometry_fields": [],
            "temporal_semantics": (
                "ACS5 vintages are overlapping five-year estimates, not independent "
                "annual point observations"
            ),
            "evidence_refs": [
                "https://api.census.gov/data/2024/acs/acs5/variables.html",
                "probe:api_key_boundary_and_timeout:2026-07-23",
                (
                    "https://api.censusreporter.org/1.0/data/show/latest?"
                    "table_ids=B01003%2CB19013%2CB25001%2CB23025&"
                    "geo_ids=14000US17031671600"
                ),
                artifact_ref("census_reporter_acs2024_tract_17031671600.json"),
            ],
            "requested_variables": [
                "B01003_001E",
                "B01003_001M",
                "B19013_001E",
                "B19013_001M",
                "B25001_001E",
                "B25001_001M",
                "B23025_005E",
                "B23025_005M",
            ],
            "fallback_probe_observations": {
                "authority_status": "verified_secondary_not_official_admission",
                "provider": "Census Reporter",
                "http_status": 200,
                "release_id": "acs2024_5yr",
                "release_years": "2020-2024",
                "geography": "Census Tract 6716, Cook, IL",
                "tract_geoid": "17031671600",
                "estimate_and_moe_pairs_present": True,
                "table_universes_present": True,
                "official_census_api_sample_still_required": True,
            },
        },
        {
            "source_id": "tiger_2020_illinois_tract_boundaries",
            "role": "spatial_units",
            "publisher": "United States Census Bureau",
            "canonical_url": (
                "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/"
                "tl_2020_17_tract.zip"
            ),
            "platform": "tiger_line",
            "authority_status": "verified_official",
            "access_boundary": "browser_or_waf",
            "metadata_probe_status": "pass",
            "schema_probe_status": "pass",
            "license_status": "pass",
            "time_coverage_status": "pass",
            "geography_coverage_status": "pass",
            "sample_validation_status": "pass",
            "stable_id_fields": ["GEOID"],
            "time_fields": ["boundary_vintage"],
            "geometry_fields": ["tract_polygon"],
            "temporal_semantics": (
                "fixed official 2020 Census tract definitions used for "
                "pre-treatment 2024 event adjacency"
            ),
            "evidence_refs": [
                "https://www.census.gov/geographies/mapping-files/"
                "time-series/geo/tiger-line-file.html",
                "probe:http_403:2026-07-23",
                "https://geo.fcc.gov/api/census/block/find",
                (
                    "https://api.censusreporter.org/1.0/geo/show/tiger2024?"
                    "geo_ids=14000US17031671600"
                ),
                artifact_ref("fcc_census_block_6716_s_bishop.json"),
                artifact_ref("census_reporter_tiger2024_tract_17031671600.json"),
                artifact_ref(
                    "census_reporter_tiger2024_cook_county_tracts.json"
                ),
                artifact_ref("chicago_provisional_tract_adjacency.json"),
                artifact_ref(
                    "chicago_official_tiger2020_tract_adjacency.json"
                ),
                artifact_ref(
                    "datagov_v4_tiger2020_illinois_tract_search.json"
                ),
                artifact_ref("datagov_tiger2020_illinois_harvest_raw.xml"),
                artifact_ref("chicago_official_census_tract_layer84_metadata.json"),
                artifact_ref(
                    "chicago_official_census_tract_layer84_count_probe.json"
                ),
                artifact_ref(
                    "chicago_official_census_tract_layer84_year_probe.json"
                ),
            ],
            "probe_observations": {
                "head_http_status": 403,
                "headed_browser_download_succeeded": True,
                "zip_auto_expanded_by_safari": True,
                "original_zip_bytes_preserved": False,
                "downloaded_component_count": 7,
                "official_catalog_identity_verified": True,
                "official_catalog_publisher": (
                    "U.S. Department of Commerce, U.S. Census Bureau, "
                    "Geography Division, Spatial Data Collection and "
                    "Products Branch"
                ),
                "official_catalog_title": (
                    "TIGER/Line Shapefile, 2020, State, Illinois, "
                    "Census Tracts"
                ),
                "official_catalog_license": (
                    "https://creativecommons.org/publicdomain/zero/1.0/"
                ),
                "official_iso_metadata_verified": True,
                "official_iso_feature_type": "Census Tracts",
                "official_iso_crs": "EPSG:4269",
                "official_geometry_component_hashes_verified": True,
                "official_statewide_tract_count": official_geometry[
                    "source_feature_count"
                ],
                "official_cook_tract_count": official_geometry[
                    "cook_county_feature_count"
                ],
                "official_geometry_crs": official_geometry[
                    "coordinate_reference_system"
                ],
                "official_geoid_fields_verified": True,
                "fcc_2020_block_lookup_http_status": 200,
                "fcc_2020_block_fips": "170316716001013",
                "fcc_2020_tract_geoid": "17031671600",
                "secondary_tiger2024_geometry_http_status": 200,
                "secondary_tiger2024_geometry_type": "Polygon",
                "secondary_tiger2024_geoid": "17031671600",
                "official_point_inside_secondary_polygon": True,
                "secondary_full_cook_geometry_verified": (
                    provisional_readiness[
                        "secondary_full_cook_geometry_verified"
                    ]
                ),
                "secondary_cook_tract_count": provisional_graph["node_count"],
                "secondary_target_tract_count": provisional_target[
                    "distinct_tract_count"
                ],
                "secondary_geometry_not_official_tiger_admission": True,
                "city_census_tract_candidate_feature_count": 878,
                "city_census_tract_candidate_year": 2000,
                "city_census_tract_candidate_rejected_for_2020_panel": True,
            },
        },
        {
            "source_id": "tiger2020_chicago_city_tract_adjacency",
            "role": "interference_network",
            "publisher": "GWM derived from official U.S. Census Bureau TIGER/Line",
            "canonical_url": (
                "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/"
                "tl_2020_17_tract.zip"
            ),
            "platform": "derived_official_shapefile_topology",
            "authority_status": "verified_official",
            "derivation_status": "deterministic_from_verified_official_geometry",
            "access_boundary": "browser_or_waf",
            "metadata_probe_status": "pass",
            "schema_probe_status": "pass",
            "license_status": "pass",
            "time_coverage_status": "pass",
            "geography_coverage_status": "pass",
            "sample_validation_status": "pass",
            "stable_id_fields": ["source_GEOID", "target_GEOID"],
            "time_fields": ["network_vintage"],
            "geometry_fields": ["shared_boundary"],
            "temporal_semantics": (
                "fixed official 2020 topology precedes all preregistered "
                "2024 events and is admitted for Chicago city-internal exposure "
                "mapping across Cook and DuPage counties"
            ),
            "evidence_refs": [
                "source:tiger_2020_illinois_tract_boundaries",
                artifact_ref(
                    "chicago_official_tiger2020_city_tract_adjacency.json"
                ),
                artifact_ref(
                    "tiger2020_illinois_tract/tl_2020_17_tract.cpg"
                ),
                artifact_ref(
                    "tiger2020_illinois_tract/tl_2020_17_tract.dbf"
                ),
                artifact_ref(
                    "tiger2020_illinois_tract/tl_2020_17_tract.prj"
                ),
                artifact_ref(
                    "tiger2020_illinois_tract/tl_2020_17_tract.shp"
                ),
                artifact_ref(
                    "tiger2020_illinois_tract/tl_2020_17_tract.shp.ea.iso.xml"
                ),
                artifact_ref(
                    "tiger2020_illinois_tract/tl_2020_17_tract.shp.iso.xml"
                ),
                artifact_ref(
                    "tiger2020_illinois_tract/tl_2020_17_tract.shx"
                ),
                artifact_ref("historical_cohort_spatial_crosswalk.json"),
            ],
            "probe_observations": {
                "official_statewide_tract_count": official_geometry[
                    "source_feature_count"
                ],
                "official_chicago_city_tract_count": city_graph["node_count"],
                "official_chicago_cook_tract_count": city_units[
                    "cook_tract_count"
                ],
                "official_chicago_dupage_tract_count": city_units[
                    "dupage_tract_count"
                ],
                "official_queen_edge_count": city_graph[
                    "queen_edge_count"
                ],
                "official_rook_edge_count": city_graph["rook_edge_count"],
                "official_queen_connected_component_count": city_graph[
                    "queen_connected_component_count"
                ],
                "official_rook_connected_component_count": city_graph[
                    "rook_connected_component_count"
                ],
                "official_queen_isolated_node_count": city_graph[
                    "queen_isolated_node_count"
                ],
                "official_rook_isolated_node_count": city_graph[
                    "rook_isolated_node_count"
                ],
                "official_topology_quality_pass": city_quality["passed"],
                "target_event_count": city_target["event_count"],
                "target_distinct_tract_count": city_target[
                    "distinct_tract_count"
                ],
                "target_tracts_with_zero_rook_neighbors": city_target[
                    "tracts_with_zero_rook_neighbors"
                ],
                "official_cook_dupage_city_internal_network_ready": (
                    city_readiness[
                        "official_cook_dupage_city_adjacency_constructed"
                    ]
                ),
                "network_to_unit_time_ready": city_readiness[
                    "network_to_unit_time_ready"
                ],
                "outside_city_interference_ready": False,
                "dynamic_network_ready": False,
                "causal_estimation_ready": False,
            },
        },
    ]
    crosswalk_evidence: dict[str, dict[str, Any]] = {
        gate_name: {
            "passed": False,
            "evidence_refs": [],
            "details": {"reason": "source_samples_or_geometry_not_admitted"},
        }
        for gate_name in LONGITUDINAL_PANEL_CROSSWALK_GATES
    }
    crosswalk_evidence["treatment_to_unit"] = {
        "passed": False,
        "evidence_refs": [
            artifact_ref("chicago_addresspoints_6716_s_bishop.json"),
            artifact_ref("fcc_census_block_6716_s_bishop.json"),
            artifact_ref("census_reporter_tiger2024_tract_17031671600.json"),
            artifact_ref("chicago_elms_matter_O2026_0024863.json"),
            artifact_ref("chicago_elms_O2026_0024863_final_ordinance.pdf"),
            artifact_ref(
                "chicago_elms_O2026_0024863_final_ordinance_ocr.txt"
            ),
            artifact_ref(
                "chicago_elms_O2026_0024863_final_narrative_and_plans.pdf"
            ),
            artifact_ref("cook_county_parcel_2021_arcgis_item.json"),
            artifact_ref("cook_county_parcel_2021_hub_metadata.json"),
            artifact_ref("chicago_addresspoints_O2024_0012247_race.json"),
            artifact_ref(
                "chicago_addresspoints_O2024_0012532_bosworth.json"
            ),
            artifact_ref("chicago_addresspoints_O2024_0012334_troy.json"),
            artifact_ref("fcc_census_block_O2024_0012247_race.json"),
            artifact_ref("fcc_census_block_O2024_0012532_bosworth.json"),
            artifact_ref("fcc_census_block_O2024_0012334_troy.json"),
            artifact_ref("chicago_current_zoning_O2024_0012247_race.json"),
            artifact_ref(
                "chicago_current_zoning_O2024_0012532_bosworth.json"
            ),
            artifact_ref("chicago_current_zoning_O2024_0012334_troy.json"),
            artifact_ref("chicago_elms_2023_2024_zoning_cohort_raw.json"),
            artifact_ref("historical_cohort_preregistration.json"),
            artifact_ref("historical_cohort_spatial_crosswalk.json"),
            artifact_ref("historical_event_crosswalk.json"),
        ],
        "details": {
            "official_address_point_verified": True,
            "point_to_2020_census_tract_verified": True,
            "candidate_tract_geoid": "17031671600",
            "historical_candidate_point_addresses_verified": True,
            "historical_candidate_pins_verified": True,
            "historical_candidate_point_to_tract_crosswalks_verified": True,
            "historical_current_zoning_map_polygons_verified": True,
            "historical_machine_legal_parcel_polygons_verified": False,
            "expanded_preregistered_event_count": 23,
            "expanded_zoning_map_ready_count": 22,
            "expanded_point_address_ready_count": 19,
            "expanded_tract_crosswalk_ready_count": 19,
            "expanded_current_parcel_crosswalk_ready_count": 19,
            "expanded_joint_spatial_crosswalk_ready_count": 17,
            "expanded_cohort_crosswalk_complete": False,
            "historical_candidate_tract_geoids": [
                "17031243400",
                "17031300900",
                "17031830600",
            ],
            "point_inside_secondary_tiger2024_polygon": True,
            "enacted_zoning_transition_verified": True,
            "legal_treatment_boundary_verified": True,
            "affected_treatment_polygon_verified": False,
            "machine_treatment_polygon_verified": False,
            "official_cook_county_parcel_metadata_verified": True,
            "official_target_pin_geometry_sample_verified": False,
            "effective_date_verified": False,
            "reason": (
                "legal_boundary_is_not_yet_a_verified_machine_polygon_and_"
                "effective_onset_is_unresolved"
            ),
        },
    }
    crosswalk_evidence["outcome_to_unit"] = {
        "passed": False,
        "evidence_refs": [
            artifact_ref("datagov_chicago_building_permits_harvest_raw.json"),
            artifact_ref(
                "chicago_official_building_permits_changes_2019_07_09.md"
            ),
            artifact_ref(
                "chicago_official_building_permits_issue_date_2017_11_20.md"
            ),
            artifact_ref(
                "chicago_official_building_permits_contact_columns_2019_07_16.md"
            ),
            artifact_ref("chicago_official_arcgis_externalapps_directory.json"),
            artifact_ref("chicago_official_permit_mapserver_metadata.json"),
            artifact_ref("chicago_official_permit_map_layer12_metadata.json"),
            artifact_ref("chicago_building_records_2024_cohort.json"),
            *[
                artifact_ref(filename)
                for filename in BUILDING_RECORD_HTML_FILES
            ],
            *[
                artifact_ref(filename)
                for filename in SOCRATA_OUTCOME_EVIDENCE_FILES
            ],
        ],
        "details": {
            "official_catalog_metadata_verified": True,
            "official_historical_schema_semantics_verified": True,
            "official_issue_date_fallback_semantics_verified": True,
            "official_contact_field_removal_semantics_verified": True,
            "current_socrata_metadata_verified": True,
            "current_socrata_schema_verified": True,
            "official_terms_of_use_verified": True,
            "documented_candidate_census_tract_field": True,
            "current_address_level_schema_verified": True,
            "row_schema_verified": True,
            "row_sample_verified": True,
            "permit_address_fields_verified": True,
            "bounded_treated_address_to_tract_crosswalk_count": 17,
            "bounded_permit_row_count": 70,
            "bounded_snapshot_raw_row_count": 114896,
            "bounded_snapshot_complete_month_count": 42,
            "official_chicago_2020_tract_count": 801,
            "official_chicago_cook_tract_count": 799,
            "official_chicago_dupage_tract_count": 2,
            "tract_month_panel_row_count": 33642,
            "spatially_admitted_permit_row_count": 114816,
            "spatial_assignment_admitted_share": 0.999303718,
            "spatially_unresolved_permit_row_count": 72,
            "state_plane_recovered_permit_row_count": 1542,
            "exact_address_geocoder_recovered_permit_row_count": 44,
            "pin_parcel_recovered_permit_row_count": remaining_pin[
                "admitted_row_count"
            ],
            "ohare_facility_context_row_count": remaining_facility[
                "context_row_count"
            ],
            "ohare_facility_point_used_as_permit_location": False,
            "fuzzy_address_geocoder_matches_admitted": False,
            "spatial_missingness_assumed_random": False,
            "outside_chicago_permit_row_count": 8,
            "tract_month_outcome_panel_materialized": True,
            "candidate_control_outcomes_materialized": True,
            "complete_tract_permit_universe_verified": False,
            "untreated_control_outcomes_verified": False,
            "public_way_use_permits_rejected_as_building_outcome": True,
            "reason": (
                "bounded_official_panel_has_99_930372_percent_spatial_coverage_"
                "but_72_rows_remain_unresolved_and_candidate_controls_are_not_"
                "verified_globally_untreated"
            ),
        },
    }
    crosswalk_evidence["confounder_to_unit"] = {
        "passed": False,
        "evidence_refs": [
            artifact_ref("census_reporter_acs2024_tract_17031671600.json"),
            artifact_ref("census_reporter_tiger2024_tract_17031671600.json"),
            artifact_ref(
                "chicago_official_tiger2020_city_tract_adjacency.json"
            ),
        ],
        "details": {
            "secondary_estimate_moe_sample_verified": True,
            "secondary_geometry_sample_verified": True,
            "tract_geoid": "17031671600",
            "official_acs_sample_verified": False,
            "official_tiger_geometry_verified": True,
            "reason": "official_acs_sample_and_longitudinal_confounders_missing",
        },
    }
    crosswalk_evidence["unit_time_alignment"] = {
        "passed": False,
        "evidence_refs": [
            artifact_ref("chicago_elms_matter_O2026_0024863.json"),
            artifact_ref("datagov_chicago_building_permits_harvest_raw.json"),
            artifact_ref(
                "chicago_building_permits_2023_2026_tract_month_panel.json"
            ),
        ],
        "details": {
            "target_cadence": "monthly",
            "passage_timestamp": "2026-07-15T15:00:00+00:00",
            "elms_last_publication_timestamp": "2026-07-17T14:25:18+00:00",
            "latest_official_permit_catalog_date": "2026-07-21",
            "complete_post_treatment_months_available": 0,
            "effective_date_verified": False,
            "candidate_temporal_role": (
                "crosswalk_fixture_not_effect_estimation_pilot"
            ),
            "reason": "no_complete_monthly_post_treatment_period",
        },
    }
    crosswalk_evidence["network_to_unit_time"] = {
        "passed": True,
        "evidence_refs": [
            artifact_ref("datagov_v4_tiger2020_illinois_tract_search.json"),
            artifact_ref("datagov_tiger2020_illinois_harvest_raw.xml"),
            artifact_ref("census_reporter_tiger2024_cook_county_tracts.json"),
            artifact_ref("chicago_provisional_tract_adjacency.json"),
            artifact_ref(
                "chicago_official_tiger2020_city_tract_adjacency.json"
            ),
            artifact_ref("historical_cohort_spatial_crosswalk.json"),
        ],
        "details": {
            "official_tiger2020_catalog_identity_verified": True,
            "official_tiger2020_iso_metadata_verified": True,
            "official_tiger2020_license_verified": True,
            "official_tiger2020_declared_crs": "EPSG:4269",
            "official_tiger2020_component_hashes_verified": True,
            "official_tiger2020_geometry_verified": True,
            "official_statewide_tract_count": official_geometry[
                "source_feature_count"
            ],
            "official_chicago_city_tract_count": city_graph["node_count"],
            "official_chicago_cook_tract_count": city_units["cook_tract_count"],
            "official_chicago_dupage_tract_count": city_units[
                "dupage_tract_count"
            ],
            "secondary_full_cook_geometry_verified": True,
            "secondary_topology_quality_pass": False,
            "target_event_count": city_target["event_count"],
            "target_distinct_tract_count": city_target[
                "distinct_tract_count"
            ],
            "all_target_tracts_present": city_target["missing_target_tracts"]
            == [],
            "official_queen_edge_count": city_graph["queen_edge_count"],
            "official_rook_edge_count": city_graph["rook_edge_count"],
            "official_queen_connected_component_count": city_graph[
                "queen_connected_component_count"
            ],
            "official_rook_connected_component_count": city_graph[
                "rook_connected_component_count"
            ],
            "official_topology_quality_pass": city_quality["passed"],
            "target_tracts_with_zero_rook_neighbors": city_target[
                "tracts_with_zero_rook_neighbors"
            ],
            "official_adjacency_constructed": True,
            "official_cook_internal_interference_network_usable": True,
            "official_cook_dupage_city_internal_network_ready": True,
            "outside_city_interference_ready": False,
            "dynamic_network_ready": False,
            "reason": (
                "official_fixed_2020_chicago_city_internal_topology_admitted_"
                "across_cook_and_dupage_but_outside_city_interference_missing"
            ),
        },
    }
    crosswalk_evidence["no_future_information_leakage"] = {
        "passed": False,
        "evidence_refs": [
            artifact_ref(
                "chicago_official_tiger2020_city_tract_adjacency.json"
            ),
            artifact_ref(
                "chicago_building_permits_2023_2026_tract_month_panel.json"
            ),
        ],
        "details": {
            "network_time_mode": "fixed_2020_official_tiger_geometry",
            "event_year": 2024,
            "historical_network_vintage_verified": True,
            "network_future_geometry_change_excluded": True,
            "full_panel_information_leakage_verified": False,
            "outcome_current_status_fields_excluded": True,
            "outcome_panel_materialized": True,
            "reason": (
                "network_and_outcome_fields_have_bounded_time_semantics_but_"
                "treatment_onsets_and_longitudinal_confounders_are_not_ready"
            ),
        },
    }
    return build_longitudinal_panel_source_contract(
        candidate={
            "candidate_id": "gwm_chicago_zoning_longitudinal_panel_v0",
            "domain_instance": "UWM_chicago_pilot",
            "geography": "Chicago, Illinois, United States",
            "target_unit": "2020_census_tract",
            "target_cadence": "monthly",
            "treatment_definition": (
                "final enacted zoning reclassification mapped to affected tract-months"
            ),
            "outcome_definition": (
                "subsequent building permit events aggregated by tract-month"
            ),
        },
        sources=sources,
        crosswalk_evidence=crosswalk_evidence,
        probe_policy={
            "probe_only": False,
            "full_download_authorized": False,
            "bounded_bulk_download_authorized": True,
            "bulk_download_performed": True,
            "bounded_socrata_snapshot_performed": True,
            "bounded_socrata_snapshot_row_count": 114896,
            "outcome_panel_materialized": True,
            "official_tiger_statewide_asset_download_performed": True,
            "official_tiger_downloaded_bytes": sum(
                evidence_artifacts[filename]["bytes"]
                for filename in (
                    "tiger2020_illinois_tract/tl_2020_17_tract.cpg",
                    "tiger2020_illinois_tract/tl_2020_17_tract.dbf",
                    "tiger2020_illinois_tract/tl_2020_17_tract.prj",
                    "tiger2020_illinois_tract/tl_2020_17_tract.shp",
                    "tiger2020_illinois_tract/tl_2020_17_tract.shp.ea.iso.xml",
                    "tiger2020_illinois_tract/tl_2020_17_tract.shp.iso.xml",
                    "tiger2020_illinois_tract/tl_2020_17_tract.shx",
                )
            ),
            "original_tiger_zip_bytes_preserved": False,
            "training_panel_materialized": False,
            "attachment_saved_to_project": True,
            "bounded_official_documents_saved_to_project": True,
            "single_attachment_full_transfer_to_null": True,
            "building_records_user_agreement_accepted": True,
            "bounded_building_record_address_queries": 17,
            "full_tract_building_permit_export_performed": True,
        },
        provenance={
            "top_level_skill": "urban-data-seeker",
            "route_type": "exact_source_browser_acquisition_and_platform_probe",
            "selected_skills": [
                "browser-automation",
                "legistar-platform",
                "socrata-platform",
                "document-portal-platform",
                "census-acs",
                "us-tiger-boundaries",
                "arcgis-platform",
                "data-gov-catalog",
                "ckan-platform",
            ],
            "probed_at": "2026-07-24T04:21:46Z",
            "response_artifacts_saved": True,
            "bounded_response_artifact_count": len(evidence_artifacts),
            "evidence_artifacts": evidence_artifacts,
            "data_foundation_audit": {
                "status": data_foundation_audit["status"],
                "report_digest": data_foundation_audit["report_digest"],
                "evidence_ref": artifact_ref("data_foundation_audit.json"),
                "all_checks_passed": data_foundation_audit["summary"][
                    "all_checks_passed"
                ],
                "panel_materialization_ready": data_foundation_audit[
                    "admission"
                ]["panel_materialization_ready"],
                "network_to_unit_time_ready": data_foundation_audit[
                    "admission"
                ]["network_to_unit_time_ready"],
                "observed_outcome_panel_materialized": data_foundation_audit[
                    "admission"
                ]["observed_outcome_panel_materialized"],
            },
            "official_socrata_outcome_panel": {
                "dataset_id": "ydr8-5enu",
                "raw_row_count": 114896,
                "spatially_admitted_row_count": 114816,
                "spatially_unresolved_row_count": 72,
                "outside_chicago_row_count": 8,
                "spatial_assignment_admitted_share": 0.999303718,
                "state_plane_recovered_row_count": 1542,
                "exact_address_geocoder_recovered_row_count": 44,
                "pin_parcel_recovered_row_count": remaining_pin[
                    "admitted_row_count"
                ],
                "ohare_facility_context_row_count": remaining_facility[
                    "context_row_count"
                ],
                "ohare_facility_point_used_as_permit_location": False,
                "fuzzy_address_matches_admitted": False,
                "unit_count": 801,
                "cook_unit_count": 799,
                "dupage_unit_count": 2,
                "month_count": 42,
                "panel_row_count": 33642,
                "candidate_control_tract_count": 700,
                "verified_untreated_control_status_ready": False,
                "causal_estimation_ready": False,
                "evidence_ref": artifact_ref(
                    "chicago_building_permits_2023_2026_tract_month_panel.json"
                ),
            },
            "provisional_interference_network": {
                "source_authority": (
                    "verified_secondary_not_official_admission"
                ),
                "cook_tract_count": provisional_graph["node_count"],
                "queen_edge_count": provisional_graph["queen_edge_count"],
                "rook_edge_count": provisional_graph["rook_edge_count"],
                "queen_connected_component_count": provisional_graph[
                    "queen_connected_component_count"
                ],
                "rook_connected_component_count": provisional_graph[
                    "rook_connected_component_count"
                ],
                "target_tract_count": provisional_target[
                    "distinct_tract_count"
                ],
                "topology_quality_pass": provisional_quality["passed"],
                "official_adjacency_constructed": False,
                "network_to_unit_time_ready": False,
                "evidence_ref": artifact_ref(
                    "chicago_provisional_tract_adjacency.json"
                ),
            },
            "official_tiger2020_preflight": {
                "catalog_identity_verified": True,
                "iso_metadata_verified": True,
                "publisher_verified": True,
                "license_verified": True,
                "geography_verified": True,
                "declared_feature_type": "Census Tracts",
                "declared_crs": "EPSG:4269",
                "zip_url_verified": True,
                "headed_browser_download_succeeded": True,
                "zip_auto_expanded_by_safari": True,
                "original_zip_bytes_preserved": False,
                "component_level_hashes_verified": True,
                "geometry_sample_verified": True,
                "official_statewide_tract_count": official_geometry[
                    "source_feature_count"
                ],
                "official_cook_tract_count": official_graph["node_count"],
                "evidence_refs": [
                    artifact_ref(
                        "datagov_v4_tiger2020_illinois_tract_search.json"
                    ),
                    artifact_ref(
                        "datagov_tiger2020_illinois_harvest_raw.xml"
                    ),
                    artifact_ref(
                        "chicago_official_tiger2020_tract_adjacency.json"
                    ),
                ],
            },
            "official_interference_network": {
                "source_authority": "verified_official_derived",
                "network_vintage": 2020,
                "scope": "Chicago city internal across Cook and DuPage counties",
                "city_tract_count": city_graph["node_count"],
                "cook_city_tract_count": city_units["cook_tract_count"],
                "dupage_city_tract_count": city_units["dupage_tract_count"],
                "queen_edge_count": city_graph["queen_edge_count"],
                "rook_edge_count": city_graph["rook_edge_count"],
                "queen_connected_component_count": city_graph[
                    "queen_connected_component_count"
                ],
                "rook_connected_component_count": city_graph[
                    "rook_connected_component_count"
                ],
                "target_tract_count": city_target[
                    "distinct_tract_count"
                ],
                "topology_quality_pass": city_quality["passed"],
                "network_to_unit_time_ready": city_readiness[
                    "network_to_unit_time_ready"
                ],
                "cook_dupage_city_internal_network_ready": True,
                "outside_city_interference_ready": False,
                "dynamic_network_ready": False,
                "causal_estimation_ready": False,
                "evidence_ref": artifact_ref(
                    "chicago_official_tiger2020_city_tract_adjacency.json"
                ),
            },
            "remaining_spatial_adjudication": {
                "remaining_unresolved_row_count": (
                    remaining_spatial_adjudication[
                        "remaining_unresolved_row_count"
                    ]
                ),
                "pin_bearing_row_count": remaining_pin[
                    "pin_bearing_row_count"
                ],
                "pin_returned_polygon_count": remaining_pin[
                    "returned_unique_pin_polygon_count"
                ],
                "pin_address_consistent_row_count": remaining_pin[
                    "address_consistent_row_count"
                ],
                "pin_spatial_recovery_ready": remaining_readiness[
                    "pin_spatial_recovery_ready"
                ],
                "facility_context_row_count": remaining_facility[
                    "context_row_count"
                ],
                "facility_level_permit_tract_assignment_ready": (
                    remaining_readiness[
                        "facility_level_permit_tract_assignment_ready"
                    ]
                ),
                "complete_spatial_assignment_ready": False,
                "evidence_ref": artifact_ref(
                    "chicago_building_permits_remaining_spatial_adjudication.json"
                ),
            },
            "historical_candidate_screening": {
                "status": (
                    "outcome_panel_materialized_but_spatial_completeness_"
                    "untreated_status_parcel_and_onset_blocked"
                ),
                "candidate_record_numbers": [
                    "O2024-0012247",
                    "O2024-0012334",
                    "O2024-0012532",
                ],
                "candidate_count": 3,
                "minimum_complete_post_publication_months": 19,
                "temporal_screen_ready": True,
                "final_attachment_metadata_ready": True,
                "final_documents_downloaded": True,
                "bounded_official_document_bytes": 2898496,
                "final_document_evidence_ready": True,
                "legal_boundary_text_ready": True,
                "zoning_transition_text_ready": True,
                "official_point_addresses_ready": True,
                "official_pins_ready": True,
                "point_to_tract_crosswalks_ready": True,
                "current_zoning_map_polygons_ready": True,
                "expanded_preregistered_event_count": 23,
                "expanded_zoning_map_ready_count": 22,
                "expanded_point_address_ready_count": 19,
                "expanded_tract_crosswalk_ready_count": 19,
                "expanded_current_parcel_crosswalk_ready_count": 19,
                "expanded_joint_spatial_crosswalk_ready_count": 17,
                "bounded_treated_address_outcome_count": 17,
                "bounded_permit_row_count": 70,
                "bounded_post_publication_permit_row_count": 18,
                "candidate_control_outcomes_materialized": True,
                "complete_tract_permit_universe_ready": False,
                "untreated_control_outcomes_ready": False,
                "expanded_missing_zoning_map_records": [
                    "O2024-0013362"
                ],
                "expanded_point_polygon_mismatch_records": [
                    "O2024-0012332"
                ],
                "expanded_cohort_crosswalk_complete": False,
                "historical_candidate_tract_geoids": [
                    "17031243400",
                    "17031300900",
                    "17031830600",
                ],
                "machine_treatment_geometries_ready": False,
                "effective_onsets_ready": False,
                "source_and_crosswalk_ready": False,
                "cohort_panel_ready": False,
                "causal_estimation_ready": False,
                "evidence_refs": [
                    artifact_ref(
                        "chicago_elms_pre2025_zoning_with_exhibits.json"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012247_race_detail.json"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012532_bosworth_detail.json"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012334_troy_detail.json"
                    ),
                    artifact_ref(
                        "chicago_elms_historical_candidate_attachment_preflight.json"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012247_final_ordinance.pdf"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012247_final_ordinance_ocr.txt"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012247_final_narrative_and_plans.pdf"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012247_final_narrative_and_plans_ocr.txt"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012532_final_ordinance.pdf"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012532_final_ordinance_ocr.txt"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012532_final_narrative_and_plans.pdf"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012532_final_narrative_and_plans_ocr.txt"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012334_final_ordinance.pdf"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012334_final_ordinance_ocr.txt"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012334_final_narrative_and_plans.pdf"
                    ),
                    artifact_ref(
                        "chicago_elms_O2024_0012334_final_narrative_and_plans_ocr.txt"
                    ),
                    artifact_ref(
                        "chicago_addresspoints_O2024_0012247_race.json"
                    ),
                    artifact_ref(
                        "chicago_addresspoints_O2024_0012532_bosworth.json"
                    ),
                    artifact_ref(
                        "chicago_addresspoints_O2024_0012334_troy.json"
                    ),
                    artifact_ref(
                        "fcc_census_block_O2024_0012247_race.json"
                    ),
                    artifact_ref(
                        "fcc_census_block_O2024_0012532_bosworth.json"
                    ),
                    artifact_ref(
                        "fcc_census_block_O2024_0012334_troy.json"
                    ),
                    artifact_ref(
                        "chicago_current_zoning_O2024_0012247_race.json"
                    ),
                    artifact_ref(
                        "chicago_current_zoning_O2024_0012532_bosworth.json"
                    ),
                    artifact_ref(
                        "chicago_current_zoning_O2024_0012334_troy.json"
                    ),
                    artifact_ref(
                        "chicago_elms_2023_2024_zoning_cohort_raw.json"
                    ),
                    artifact_ref("historical_cohort_preregistration.json"),
                    artifact_ref("historical_cohort_spatial_crosswalk.json"),
                    artifact_ref("historical_event_crosswalk.json"),
                    artifact_ref("chicago_building_records_2024_cohort.json"),
                ],
            },
            "network_requests_bounded_to_metadata_and_samples": False,
            "latest_probe_requests_bounded_to_metadata_and_samples": False,
            "latest_socrata_acquisition_is_bounded_complete_window": True,
            "latest_socrata_snapshot_row_count": 114896,
            "latest_outcome_panel_materialized": True,
            "latest_building_records_probe_address_count": 17,
            "latest_building_records_probe_row_count": 70,
            "latest_building_records_full_tract_export_performed": False,
            "latest_acquisition_bounded_to_two_official_documents": True,
            "bounded_official_document_bytes": 318554,
            "historical_bounded_official_document_bytes": 2898496,
            "cumulative_bounded_official_document_bytes": 3217050,
            "latest_schema_semantics_requests_bounded_to_four_official_docs": True,
            "latest_historical_screen_bounded_to_one_page_and_three_details": True,
            "single_attachment_full_transfer_to_null": True,
            "candidate_temporal_role": (
                "crosswalk_fixture_not_effect_estimation_pilot"
            ),
        },
    )


def _evidence_artifact_manifest() -> dict[str, dict[str, Any]]:
    manifest = {}
    for filename in EVIDENCE_FILES:
        path = EVIDENCE_DIR / filename
        payload = path.read_bytes()
        manifest[filename] = {
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    contract = build_chicago_longitudinal_panel_source_candidate()
    validation = validate_longitudinal_panel_source_contract(contract)
    if not validation["valid"]:
        raise SystemExit(
            "invalid candidate contract: " + ", ".join(validation["errors"])
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
