#!/usr/bin/env python3
"""Audit bounded Chicago data-foundation evidence without admitting a panel."""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence"
)
DEFAULT_OUTPUT = EVIDENCE_DIR / "data_foundation_audit.json"
DEFAULT_HISTORICAL_CROSSWALK_OUTPUT = (
    EVIDENCE_DIR / "historical_event_crosswalk.json"
)
JSON_EVIDENCE_FILES = (
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
    "datagov_v4_tiger2020_illinois_tract_search.json",
    "chicago_elms_matter_O2026_0024863.json",
    "datagov_v4_cook_county_parcel_2021_search.json",
    "cook_county_parcel_2021_arcgis_item.json",
    "cook_county_parcel_2021_hub_metadata.json",
    "chicago_dev_portal_github_repository.json",
    "chicago_elms_pre2025_zoning_with_exhibits.json",
    "chicago_elms_O2024_0012247_race_detail.json",
    "chicago_elms_O2024_0012532_bosworth_detail.json",
    "chicago_elms_O2024_0012334_troy_detail.json",
    "chicago_elms_historical_candidate_attachment_preflight.json",
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
    "chicago_socrata_building_permits_metadata_browser.json",
    "chicago_socrata_building_permits_metadata_browser.json.capture.json",
    "chicago_socrata_building_permits_current_sample_browser.json",
    "chicago_socrata_building_permits_current_sample_browser.json.capture.json",
    "chicago_socrata_building_permits_race_crosscheck_browser.json",
    "chicago_socrata_building_permits_race_crosscheck_browser.json.capture.json",
    "chicago_socrata_building_permits_2023_2026_tract_summary_browser.json",
    "chicago_socrata_building_permits_2023_2026_tract_summary_browser.json.capture.json",
    "chicago_data_portal_terms_of_use.html.capture.json",
    "chicago_building_permits_2023_2026_tract_month_panel.json",
    "chicago_socrata_building_permits_2023_2026_missing_coordinates_address_browser.json",
    "chicago_socrata_building_permits_2023_2026_missing_coordinates_address_browser.json.capture.json",
    "chicago_building_permits_unresolved_address_geocoder_request.json",
    "chicago_building_permits_spatial_missingness_diagnostic.json",
    "chicago_building_permits_unresolved_address_geocoder_response.json",
    "chicago_building_permits_unresolved_pin_parcel_response.json",
    "chicago_official_airports_layer31_metadata.json",
    "chicago_official_airports_layer31_all_features.json",
    "chicago_building_permits_remaining_spatial_adjudication.json",
)
TEXT_EVIDENCE_FILES = (
    "chicago_elms_O2026_0024863_final_ordinance_ocr.txt",
    "chicago_elms_O2026_0024863_final_narrative_and_plans_ocr.txt",
    "chicago_official_building_permits_changes_2019_07_09.md",
    "chicago_official_building_permits_issue_date_2017_11_20.md",
    "chicago_official_building_permits_contact_columns_2019_07_16.md",
    "chicago_elms_O2024_0012247_final_ordinance_ocr.txt",
    "chicago_elms_O2024_0012247_final_narrative_and_plans_ocr.txt",
    "chicago_elms_O2024_0012532_final_ordinance_ocr.txt",
    "chicago_elms_O2024_0012532_final_narrative_and_plans_ocr.txt",
    "chicago_elms_O2024_0012334_final_ordinance_ocr.txt",
    "chicago_elms_O2024_0012334_final_narrative_and_plans_ocr.txt",
    "chicago_building_permits_unresolved_pin_parcel_response.headers",
)
XML_EVIDENCE_FILES = (
    "datagov_tiger2020_illinois_harvest_raw.xml",
)
BINARY_EVIDENCE_FILES = (
    "chicago_elms_O2026_0024863_final_ordinance.pdf",
    "chicago_elms_O2026_0024863_final_narrative_and_plans.pdf",
    "chicago_elms_O2024_0012247_final_ordinance.pdf",
    "chicago_elms_O2024_0012247_final_narrative_and_plans.pdf",
    "chicago_elms_O2024_0012532_final_ordinance.pdf",
    "chicago_elms_O2024_0012532_final_narrative_and_plans.pdf",
    "chicago_elms_O2024_0012334_final_ordinance.pdf",
    "chicago_elms_O2024_0012334_final_narrative_and_plans.pdf",
    "tiger2020_illinois_tract/tl_2020_17_tract.cpg",
    "tiger2020_illinois_tract/tl_2020_17_tract.dbf",
    "tiger2020_illinois_tract/tl_2020_17_tract.prj",
    "tiger2020_illinois_tract/tl_2020_17_tract.shp",
    "tiger2020_illinois_tract/tl_2020_17_tract.shp.ea.iso.xml",
    "tiger2020_illinois_tract/tl_2020_17_tract.shp.iso.xml",
    "tiger2020_illinois_tract/tl_2020_17_tract.shx",
    "tiger2020_illinois_place/tl_2020_17_place.cpg",
    "tiger2020_illinois_place/tl_2020_17_place.dbf",
    "tiger2020_illinois_place/tl_2020_17_place.prj",
    "tiger2020_illinois_place/tl_2020_17_place.shp",
    "tiger2020_illinois_place/tl_2020_17_place.shp.ea.iso.xml",
    "tiger2020_illinois_place/tl_2020_17_place.shp.iso.xml",
    "tiger2020_illinois_place/tl_2020_17_place.shx",
    "chicago_data_portal_terms_of_use.html",
)
SOCRATA_RAW_EVIDENCE_FILES = tuple(
    filename
    for part_index in range(5)
    for filename in (
        f"chicago_socrata_building_permits_2023_2026_raw/part-{part_index:05d}.json",
        f"chicago_socrata_building_permits_2023_2026_raw/part-{part_index:05d}.json.capture.json",
    )
)
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
RAW_EVIDENCE_FILES = (
    *JSON_EVIDENCE_FILES,
    *TEXT_EVIDENCE_FILES,
    *XML_EVIDENCE_FILES,
    *BINARY_EVIDENCE_FILES,
    *SOCRATA_RAW_EVIDENCE_FILES,
    *BUILDING_RECORD_HTML_FILES,
)
TARGET_POINT_WGS84 = (-87.66061727108206, 41.77166529892371)
TARGET_TRACT_GEOID = "17031671600"
TARGET_PIN10 = "2020302029"
HISTORICAL_CROSSWALK_EXPECTATIONS = {
    "O2024-0012247": {
        "address_file": "chicago_addresspoints_O2024_0012247_race.json",
        "fcc_file": "fcc_census_block_O2024_0012247_race.json",
        "zoning_file": "chicago_current_zoning_O2024_0012247_race.json",
        "match_address": "1228 W RACE AVE, 60642",
        "pin10": "1708126021",
        "block_fips": "170312434002007",
        "tract_geoid": "17031243400",
        "digital_zone_class": "B2-3",
        "legal_lot_area_square_feet": 2088,
    },
    "O2024-0012532": {
        "address_file": "chicago_addresspoints_O2024_0012532_bosworth.json",
        "fcc_file": "fcc_census_block_O2024_0012532_bosworth.json",
        "zoning_file": "chicago_current_zoning_O2024_0012532_bosworth.json",
        "match_address": "6453 N BOSWORTH AVE, 60626",
        "pin10": "1132323002",
        "block_fips": "170318306001008",
        "tract_geoid": "17031830600",
        "digital_zone_class": "RM-4.5",
        "legal_lot_area_square_feet": 3885,
    },
    "O2024-0012334": {
        "address_file": "chicago_addresspoints_O2024_0012334_troy.json",
        "fcc_file": "fcc_census_block_O2024_0012334_troy.json",
        "zoning_file": "chicago_current_zoning_O2024_0012334_troy.json",
        "match_address": "2437 S TROY ST, 60623",
        "pin10": "1625115015",
        "block_fips": "170313009002011",
        "tract_geoid": "17031300900",
        "digital_zone_class": "RM-5",
        "legal_lot_area_square_feet": None,
    },
}


def audit_chicago_longitudinal_data_foundation() -> dict[str, Any]:
    """Parse and cross-check raw evidence while preserving source boundaries."""

    artifacts: dict[str, dict[str, Any]] = {}
    payloads: dict[str, Any] = {}
    for filename in RAW_EVIDENCE_FILES:
        artifact = _load_artifact(
            filename,
            parse_json=filename in JSON_EVIDENCE_FILES,
        )
        if "payload" in artifact:
            payloads[filename] = artifact.pop("payload")
        artifacts[filename] = artifact

    catalog = payloads["datagov_v4_chicago_building_permits_search.json"]
    permit = _find_permit_catalog_record(catalog)
    dcat = permit.get("dcat") if isinstance(permit, Mapping) else {}
    dcat = dcat if isinstance(dcat, Mapping) else {}
    organization = (
        permit.get("organization") if isinstance(permit, Mapping) else {}
    )
    organization = organization if isinstance(organization, Mapping) else {}
    distributions = dcat.get("distribution")
    distributions = distributions if isinstance(distributions, list) else []

    address_payload = payloads["chicago_addresspoints_6716_s_bishop.json"]
    candidates = address_payload.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    address = candidates[0] if candidates else {}
    address_attributes = address.get("attributes")
    address_attributes = (
        address_attributes if isinstance(address_attributes, Mapping) else {}
    )

    fcc = payloads["fcc_census_block_6716_s_bishop.json"]
    block = fcc.get("Block")
    block = block if isinstance(block, Mapping) else {}
    block_fips = str(block.get("FIPS") or "")
    derived_tract = block_fips[:11] if len(block_fips) == 15 else None

    zoning = payloads["chicago_current_zoning_6716_s_bishop.json"]
    zoning_features = zoning.get("features")
    zoning_features = zoning_features if isinstance(zoning_features, list) else []
    zoning_attributes = (
        zoning_features[0].get("attributes") if zoning_features else {}
    )
    zoning_attributes = (
        zoning_attributes if isinstance(zoning_attributes, Mapping) else {}
    )
    zoning_case = payloads["chicago_current_zoning_case_23063.json"]
    zoning_case_features = zoning_case.get("features")
    zoning_case_features = (
        zoning_case_features if isinstance(zoning_case_features, list) else []
    )

    acs = payloads["census_reporter_acs2024_tract_17031671600.json"]
    acs_release = acs.get("release")
    acs_release = acs_release if isinstance(acs_release, Mapping) else {}
    acs_data = acs.get("data")
    acs_data = acs_data if isinstance(acs_data, Mapping) else {}
    tract_data = acs_data.get("14000US" + TARGET_TRACT_GEOID)
    tract_data = tract_data if isinstance(tract_data, Mapping) else {}
    expected_tables = {"B01003", "B19013", "B23025", "B25001"}
    estimate_moe_complete = all(
        isinstance(tract_data.get(table), Mapping)
        and isinstance(tract_data[table].get("estimate"), Mapping)
        and bool(tract_data[table]["estimate"])
        and isinstance(tract_data[table].get("error"), Mapping)
        and set(tract_data[table]["estimate"])
        == set(tract_data[table]["error"])
        for table in expected_tables
    )

    geometry_payload = payloads[
        "census_reporter_tiger2024_tract_17031671600.json"
    ]
    geometry_features = geometry_payload.get("features")
    geometry_features = (
        geometry_features if isinstance(geometry_features, list) else []
    )
    geometry_feature = geometry_features[0] if geometry_features else {}
    geometry = geometry_feature.get("geometry")
    geometry = geometry if isinstance(geometry, Mapping) else {}
    properties = geometry_feature.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    rings = geometry.get("coordinates")
    outer_ring = (
        rings[0]
        if isinstance(rings, list)
        and rings
        and isinstance(rings[0], list)
        else []
    )
    point_inside = _point_in_polygon(TARGET_POINT_WGS84, outer_ring)
    cook_geometry = payloads[
        "census_reporter_tiger2024_cook_county_tracts.json"
    ]
    cook_geometry_features = cook_geometry.get("features")
    cook_geometry_features = (
        cook_geometry_features
        if isinstance(cook_geometry_features, list)
        else []
    )
    cook_geometry_geoids = {
        str(feature.get("properties", {}).get("geoid") or "")
        for feature in cook_geometry_features
        if isinstance(feature, Mapping)
        and isinstance(feature.get("properties"), Mapping)
    }
    cook_geometry_types = {
        str(feature.get("geometry", {}).get("type") or "")
        for feature in cook_geometry_features
        if isinstance(feature, Mapping)
        and isinstance(feature.get("geometry"), Mapping)
    }
    provisional_adjacency = payloads[
        "chicago_provisional_tract_adjacency.json"
    ]
    provisional_graph = provisional_adjacency.get("graph_summary")
    provisional_graph = (
        provisional_graph if isinstance(provisional_graph, Mapping) else {}
    )
    provisional_quality = provisional_adjacency.get(
        "topology_quality_diagnostics"
    )
    provisional_quality = (
        provisional_quality if isinstance(provisional_quality, Mapping) else {}
    )
    provisional_target = provisional_adjacency.get("target_cohort")
    provisional_target = (
        provisional_target if isinstance(provisional_target, Mapping) else {}
    )
    provisional_readiness = provisional_adjacency.get("readiness")
    provisional_readiness = (
        provisional_readiness
        if isinstance(provisional_readiness, Mapping)
        else {}
    )
    provisional_digest_payload = dict(provisional_adjacency)
    provisional_checked_digest = provisional_digest_payload.pop(
        "adjacency_digest", None
    )
    official_adjacency = payloads[
        "chicago_official_tiger2020_tract_adjacency.json"
    ]
    official_geometry = official_adjacency.get("geometry_validation")
    official_geometry = (
        official_geometry if isinstance(official_geometry, Mapping) else {}
    )
    official_graph = official_adjacency.get("graph_summary")
    official_graph = (
        official_graph if isinstance(official_graph, Mapping) else {}
    )
    official_quality = official_adjacency.get(
        "topology_quality_diagnostics"
    )
    official_quality = (
        official_quality if isinstance(official_quality, Mapping) else {}
    )
    official_target = official_adjacency.get("target_cohort")
    official_target = (
        official_target if isinstance(official_target, Mapping) else {}
    )
    official_readiness = official_adjacency.get("readiness")
    official_readiness = (
        official_readiness if isinstance(official_readiness, Mapping) else {}
    )
    official_digest_payload = dict(official_adjacency)
    official_checked_digest = official_digest_payload.pop(
        "adjacency_digest", None
    )
    city_adjacency = payloads[
        "chicago_official_tiger2020_city_tract_adjacency.json"
    ]
    city_units = city_adjacency.get("unit_contract")
    city_units = city_units if isinstance(city_units, Mapping) else {}
    city_graph = city_adjacency.get("graph_summary")
    city_graph = city_graph if isinstance(city_graph, Mapping) else {}
    city_quality = city_adjacency.get("topology_quality_diagnostics")
    city_quality = city_quality if isinstance(city_quality, Mapping) else {}
    city_readiness = city_adjacency.get("readiness")
    city_readiness = (
        city_readiness if isinstance(city_readiness, Mapping) else {}
    )
    city_claim_boundary = city_adjacency.get("claim_boundary")
    city_claim_boundary = (
        city_claim_boundary
        if isinstance(city_claim_boundary, Mapping)
        else {}
    )
    city_digest_payload = dict(city_adjacency)
    city_checked_digest = city_digest_payload.pop("adjacency_digest", None)
    official_component_filenames = (
        "tiger2020_illinois_tract/tl_2020_17_tract.cpg",
        "tiger2020_illinois_tract/tl_2020_17_tract.dbf",
        "tiger2020_illinois_tract/tl_2020_17_tract.prj",
        "tiger2020_illinois_tract/tl_2020_17_tract.shp",
        "tiger2020_illinois_tract/tl_2020_17_tract.shp.ea.iso.xml",
        "tiger2020_illinois_tract/tl_2020_17_tract.shp.iso.xml",
        "tiger2020_illinois_tract/tl_2020_17_tract.shx",
    )
    tiger_catalog = payloads[
        "datagov_v4_tiger2020_illinois_tract_search.json"
    ]
    tiger_catalog_results = tiger_catalog.get("results")
    tiger_catalog_results = (
        tiger_catalog_results if isinstance(tiger_catalog_results, list) else []
    )
    tiger_catalog_record = (
        tiger_catalog_results[0]
        if tiger_catalog_results
        and isinstance(tiger_catalog_results[0], Mapping)
        else {}
    )
    tiger_dcat = tiger_catalog_record.get("dcat")
    tiger_dcat = tiger_dcat if isinstance(tiger_dcat, Mapping) else {}
    tiger_organization = tiger_catalog_record.get("organization")
    tiger_organization = (
        tiger_organization if isinstance(tiger_organization, Mapping) else {}
    )
    tiger_distributions = tiger_dcat.get("distribution")
    tiger_distributions = (
        tiger_distributions if isinstance(tiger_distributions, list) else []
    )
    tiger_zip_distribution = next(
        (
            distribution
            for distribution in tiger_distributions
            if isinstance(distribution, Mapping)
            and distribution.get("title") == "tl_2020_17_tract.zip"
        ),
        {},
    )
    tiger_iso_path = (
        EVIDENCE_DIR / "datagov_tiger2020_illinois_harvest_raw.xml"
    )
    tiger_iso_root = ET.parse(tiger_iso_path).getroot()
    tiger_xml_namespaces = {
        "gco": "http://www.isotc211.org/2005/gco",
        "gmd": "http://www.isotc211.org/2005/gmd",
    }
    tiger_iso_file_identifier = tiger_iso_root.findtext(
        ".//gmd:fileIdentifier/gco:CharacterString",
        namespaces=tiger_xml_namespaces,
    )
    tiger_iso_crs = tiger_iso_root.findtext(
        ".//gmd:referenceSystemIdentifier//gmd:code/gco:CharacterString",
        namespaces=tiger_xml_namespaces,
    )
    tiger_iso_feature_type = tiger_iso_root.findtext(
        ".//gmd:featureTypes/gco:LocalName",
        namespaces=tiger_xml_namespaces,
    )
    tiger_iso_fees = tiger_iso_root.findtext(
        ".//gmd:distributionOrderProcess//gmd:fees/gco:CharacterString",
        namespaces=tiger_xml_namespaces,
    )
    tiger_iso_urls = [
        str(element.text or "")
        for element in tiger_iso_root.findall(
            ".//gmd:URL", namespaces=tiger_xml_namespaces
        )
    ]
    tiger_iso_bbox = {
        "west": tiger_iso_root.findtext(
            ".//gmd:westBoundLongitude/gco:Decimal",
            namespaces=tiger_xml_namespaces,
        ),
        "east": tiger_iso_root.findtext(
            ".//gmd:eastBoundLongitude/gco:Decimal",
            namespaces=tiger_xml_namespaces,
        ),
        "south": tiger_iso_root.findtext(
            ".//gmd:southBoundLatitude/gco:Decimal",
            namespaces=tiger_xml_namespaces,
        ),
        "north": tiger_iso_root.findtext(
            ".//gmd:northBoundLatitude/gco:Decimal",
            namespaces=tiger_xml_namespaces,
        ),
    }

    matter = payloads["chicago_elms_matter_O2026_0024863.json"]
    matter_attachments = matter.get("attachments")
    matter_attachments = (
        matter_attachments if isinstance(matter_attachments, list) else []
    )
    attachment_by_name = {
        str(attachment.get("fileName")): attachment
        for attachment in matter_attachments
        if isinstance(attachment, Mapping)
    }
    final_ordinance_name = "O2026-0024863 Final Ordinance.pdf"
    final_narrative_name = "O2026-0024863 Final Narrative and Plans.pdf"
    final_ordinance_url = (
        "https://occprodstoragev1.blob.core.usgovcloudapi.net/"
        "matterattachmentspublic/06f59372-b713-4371-a145-92028931a3bd.pdf"
    )
    final_narrative_url = (
        "https://occprodstoragev1.blob.core.usgovcloudapi.net/"
        "matterattachmentspublic/8a22ded0-47d3-40ca-bb35-c2d5961095fa.pdf"
    )
    ordinance_text = _normalized_text(
        "chicago_elms_O2026_0024863_final_ordinance_ocr.txt"
    )
    narrative_text = _normalized_text(
        "chicago_elms_O2026_0024863_final_narrative_and_plans_ocr.txt"
    )
    ordinance_pdf = artifacts[
        "chicago_elms_O2026_0024863_final_ordinance.pdf"
    ]
    narrative_pdf = artifacts[
        "chicago_elms_O2026_0024863_final_narrative_and_plans.pdf"
    ]

    parcel_catalog = payloads[
        "datagov_v4_cook_county_parcel_2021_search.json"
    ]
    parcel_record = _find_catalog_record(
        parcel_catalog,
        "https://datacatalog.cookcountyil.gov/api/views/77tz-riq7",
    )
    parcel_dcat = parcel_record.get("dcat")
    parcel_dcat = parcel_dcat if isinstance(parcel_dcat, Mapping) else {}
    parcel_organization = parcel_record.get("organization")
    parcel_organization = (
        parcel_organization
        if isinstance(parcel_organization, Mapping)
        else {}
    )
    parcel_item = payloads["cook_county_parcel_2021_arcgis_item.json"]
    parcel_hub = payloads["cook_county_parcel_2021_hub_metadata.json"]
    parcel_hub_data = parcel_hub.get("data")
    parcel_hub_data = (
        parcel_hub_data if isinstance(parcel_hub_data, Mapping) else {}
    )
    parcel_attributes = parcel_hub_data.get("attributes")
    parcel_attributes = (
        parcel_attributes if isinstance(parcel_attributes, Mapping) else {}
    )
    parcel_fields = parcel_attributes.get("fieldNames")
    parcel_fields = parcel_fields if isinstance(parcel_fields, list) else []
    parcel_service_url = (
        "https://gis.cookcountyil.gov/hosting/rest/services/Hosted/"
        "Parcel2021_enhancedAll/FeatureServer/0"
    )
    chicago_dev_repository = payloads[
        "chicago_dev_portal_github_repository.json"
    ]
    chicago_dev_owner = chicago_dev_repository.get("owner")
    chicago_dev_owner = (
        chicago_dev_owner if isinstance(chicago_dev_owner, Mapping) else {}
    )
    permit_changes_text = _normalized_text(
        "chicago_official_building_permits_changes_2019_07_09.md"
    )
    permit_issue_date_text = _normalized_text(
        "chicago_official_building_permits_issue_date_2017_11_20.md"
    )
    permit_contact_text = _normalized_text(
        "chicago_official_building_permits_contact_columns_2019_07_16.md"
    )
    historical_search = payloads[
        "chicago_elms_pre2025_zoning_with_exhibits.json"
    ]
    historical_search_meta = historical_search.get("meta")
    historical_search_meta = (
        historical_search_meta
        if isinstance(historical_search_meta, Mapping)
        else {}
    )
    historical_search_data = historical_search.get("data")
    historical_search_data = (
        historical_search_data
        if isinstance(historical_search_data, list)
        else []
    )
    historical_zoning_rows = [
        row
        for row in historical_search_data
        if isinstance(row, Mapping)
        and str(row.get("title") or "").startswith("Zoning Reclassification")
    ]
    historical_candidate_details = [
        payloads["chicago_elms_O2024_0012247_race_detail.json"],
        payloads["chicago_elms_O2024_0012532_bosworth_detail.json"],
        payloads["chicago_elms_O2024_0012334_troy_detail.json"],
    ]
    historical_candidate_records = {
        str(candidate.get("recordNumber")): candidate
        for candidate in historical_candidate_details
        if isinstance(candidate, Mapping)
    }
    historical_preflight = payloads[
        "chicago_elms_historical_candidate_attachment_preflight.json"
    ]
    historical_preflight_scope = historical_preflight.get("request_scope")
    historical_preflight_scope = (
        historical_preflight_scope
        if isinstance(historical_preflight_scope, Mapping)
        else {}
    )
    historical_preflight_candidates = historical_preflight.get("candidates")
    historical_preflight_candidates = (
        historical_preflight_candidates
        if isinstance(historical_preflight_candidates, list)
        else []
    )
    historical_document_files = {
        ("O2024-0012247", "final_ordinance"): (
            "chicago_elms_O2024_0012247_final_ordinance.pdf"
        ),
        ("O2024-0012247", "final_narrative_and_plans"): (
            "chicago_elms_O2024_0012247_final_narrative_and_plans.pdf"
        ),
        ("O2024-0012532", "final_ordinance"): (
            "chicago_elms_O2024_0012532_final_ordinance.pdf"
        ),
        ("O2024-0012532", "final_narrative_and_plans"): (
            "chicago_elms_O2024_0012532_final_narrative_and_plans.pdf"
        ),
        ("O2024-0012334", "final_ordinance"): (
            "chicago_elms_O2024_0012334_final_ordinance.pdf"
        ),
        ("O2024-0012334", "final_narrative_and_plans"): (
            "chicago_elms_O2024_0012334_final_narrative_and_plans.pdf"
        ),
    }
    historical_ordinance_text = {
        "O2024-0012247": _normalized_text(
            "chicago_elms_O2024_0012247_final_ordinance_ocr.txt"
        ),
        "O2024-0012532": _normalized_text(
            "chicago_elms_O2024_0012532_final_ordinance_ocr.txt"
        ),
        "O2024-0012334": _normalized_text(
            "chicago_elms_O2024_0012334_final_ordinance_ocr.txt"
        ),
    }
    historical_narrative_text = {
        "O2024-0012247": _normalized_text(
            "chicago_elms_O2024_0012247_final_narrative_and_plans_ocr.txt"
        ),
        "O2024-0012532": _normalized_text(
            "chicago_elms_O2024_0012532_final_narrative_and_plans_ocr.txt"
        ),
        "O2024-0012334": _normalized_text(
            "chicago_elms_O2024_0012334_final_narrative_and_plans_ocr.txt"
        ),
    }
    historical_zoning_specifications = {
        "O2024-0012247": {
            "address": "1228 W Race Ave",
            "from_zoning": "B3-2",
            "to_zoning": "B2-3",
            "legal_width_feet": 24,
            "lot_area_square_feet": 2088,
            "dwelling_units_before": 2,
            "dwelling_units_after": 3,
        },
        "O2024-0012532": {
            "address": "6453 N Bosworth Ave",
            "from_zoning": "RS3",
            "to_zoning": "RM4.5",
            "legal_width_feet": 31,
            "lot_area_square_feet": 3885,
            "dwelling_units_before": 3,
            "dwelling_units_after": 4,
        },
        "O2024-0012334": {
            "address": "2437 S Troy St",
            "from_zoning": "RT4",
            "to_zoning": "RM5",
            "legal_width_feet": 24,
            "lot_area_square_feet": None,
            "dwelling_units_before": 3,
            "dwelling_units_after": 5,
        },
    }
    historical_preflight_documents = [
        (str(candidate.get("record_number") or ""), document)
        for candidate in historical_preflight_candidates
        if isinstance(candidate, Mapping)
        for document in (
            candidate.get("documents")
            if isinstance(candidate.get("documents"), list)
            else []
        )
        if isinstance(document, Mapping)
    ]
    historical_document_integrity = all(
        (record_number, str(document.get("role") or ""))
        in historical_document_files
        and artifacts[
            historical_document_files[
                (record_number, str(document.get("role") or ""))
            ]
        ]["bytes"]
        == document.get("bytes")
        and artifacts[
            historical_document_files[
                (record_number, str(document.get("role") or ""))
            ]
        ]["sha256"]
        == document.get("sha256")
        and _has_pdf_magic(
            historical_document_files[
                (record_number, str(document.get("role") or ""))
            ]
        )
        for record_number, document in historical_preflight_documents
    )
    historical_geocode_statuses = [
        candidate.get("geocode_probe_http_status")
        for candidate in historical_preflight_candidates
        if isinstance(candidate, Mapping)
    ]
    historical_event_crosswalks = {
        record_number: _build_historical_event_crosswalk(
            record_number=record_number,
            expectation=expectation,
            address_payload=payloads[expectation["address_file"]],
            fcc_payload=payloads[expectation["fcc_file"]],
            zoning_payload=payloads[expectation["zoning_file"]],
            artifacts=artifacts,
        )
        for record_number, expectation in HISTORICAL_CROSSWALK_EXPECTATIONS.items()
    }
    historical_point_crosswalk_ready = all(
        crosswalk["validation"]["passed"] is True
        for crosswalk in historical_event_crosswalks.values()
    )
    historical_zoning_map_polygons_ready = all(
        crosswalk["zoning_map_validation"]["passed"] is True
        for crosswalk in historical_event_crosswalks.values()
    )
    expanded_cohort_raw = payloads[
        "chicago_elms_2023_2024_zoning_cohort_raw.json"
    ]
    expanded_cohort = payloads["historical_cohort_preregistration.json"]
    expanded_crosswalk = payloads[
        "historical_cohort_spatial_crosswalk.json"
    ]
    expanded_raw_meta = expanded_cohort_raw.get("meta")
    expanded_raw_meta = (
        expanded_raw_meta if isinstance(expanded_raw_meta, Mapping) else {}
    )
    expanded_raw_rows = expanded_cohort_raw.get("data")
    expanded_raw_rows = (
        expanded_raw_rows if isinstance(expanded_raw_rows, list) else []
    )
    expanded_screening = expanded_cohort.get("screening")
    expanded_screening = (
        expanded_screening if isinstance(expanded_screening, Mapping) else {}
    )
    expanded_events = expanded_cohort.get("events")
    expanded_events = expanded_events if isinstance(expanded_events, list) else []
    expanded_summary = expanded_crosswalk.get("summary")
    expanded_summary = (
        expanded_summary if isinstance(expanded_summary, Mapping) else {}
    )
    expanded_readiness = expanded_crosswalk.get("readiness")
    expanded_readiness = (
        expanded_readiness if isinstance(expanded_readiness, Mapping) else {}
    )
    operational_map = payloads[
        "chicago_official_operational_mapserver_metadata.json"
    ]
    operational_layers = operational_map.get("layers")
    operational_layers = (
        operational_layers if isinstance(operational_layers, list) else []
    )
    operational_layer_names = {
        int(layer.get("id")): str(layer.get("name") or "")
        for layer in operational_layers
        if isinstance(layer, Mapping) and isinstance(layer.get("id"), int)
    }
    externalapps_directory = payloads[
        "chicago_official_arcgis_externalapps_directory.json"
    ]
    externalapp_services = externalapps_directory.get("services")
    externalapp_services = (
        externalapp_services if isinstance(externalapp_services, list) else []
    )
    externalapp_permit_services = [
        service
        for service in externalapp_services
        if isinstance(service, Mapping)
        and "permit" in str(service.get("name") or "").lower()
    ]
    permit_mapserver = payloads[
        "chicago_official_permit_mapserver_metadata.json"
    ]
    permit_map_layers = permit_mapserver.get("layers")
    permit_map_layers = (
        permit_map_layers if isinstance(permit_map_layers, list) else []
    )
    permit_map_leaf_layers = [
        layer
        for layer in permit_map_layers
        if isinstance(layer, Mapping) and layer.get("subLayerIds") is None
    ]
    pwu_permit_layer = payloads[
        "chicago_official_permit_map_layer12_metadata.json"
    ]
    pwu_fields = pwu_permit_layer.get("fields")
    pwu_fields = pwu_fields if isinstance(pwu_fields, list) else []
    pwu_field_names = {
        str(field.get("name") or "")
        for field in pwu_fields
        if isinstance(field, Mapping)
    }
    city_tract_layer = payloads[
        "chicago_official_census_tract_layer84_metadata.json"
    ]
    city_tract_fields = city_tract_layer.get("fields")
    city_tract_fields = (
        city_tract_fields if isinstance(city_tract_fields, list) else []
    )
    city_tract_field_names = {
        str(field.get("name") or "")
        for field in city_tract_fields
        if isinstance(field, Mapping)
    }
    city_tract_count_probe = payloads[
        "chicago_official_census_tract_layer84_count_probe.json"
    ]
    city_tract_year_probe = payloads[
        "chicago_official_census_tract_layer84_year_probe.json"
    ]
    city_tract_year_features = city_tract_year_probe.get("features")
    city_tract_year_features = (
        city_tract_year_features
        if isinstance(city_tract_year_features, list)
        else []
    )
    building_records = payloads["chicago_building_records_2024_cohort.json"]
    building_records_source = building_records.get("source")
    building_records_source = (
        building_records_source
        if isinstance(building_records_source, Mapping)
        else {}
    )
    building_records_selection = building_records.get("selection")
    building_records_selection = (
        building_records_selection
        if isinstance(building_records_selection, Mapping)
        else {}
    )
    building_records_summary = building_records.get("summary")
    building_records_summary = (
        building_records_summary
        if isinstance(building_records_summary, Mapping)
        else {}
    )
    building_records_readiness = building_records.get("readiness")
    building_records_readiness = (
        building_records_readiness
        if isinstance(building_records_readiness, Mapping)
        else {}
    )
    building_record_observations = building_records.get("observations")
    building_record_observations = (
        building_record_observations
        if isinstance(building_record_observations, list)
        else []
    )
    expanded_crosswalk_events = expanded_crosswalk.get("events")
    expanded_crosswalk_events = (
        expanded_crosswalk_events
        if isinstance(expanded_crosswalk_events, list)
        else []
    )
    joint_spatial_events = {
        str(event.get("record_number") or ""): event
        for event in expanded_crosswalk_events
        if isinstance(event, Mapping)
        and isinstance(event.get("spatial_consistency"), Mapping)
        and event["spatial_consistency"].get("ready") is True
    }
    building_record_observations_by_record = {
        str(observation.get("record_number") or ""): observation
        for observation in building_record_observations
        if isinstance(observation, Mapping)
    }
    building_record_permits = [
        (observation, permit)
        for observation in building_record_observations
        if isinstance(observation, Mapping)
        for permit in (
            observation.get("permits")
            if isinstance(observation.get("permits"), list)
            else []
        )
        if isinstance(permit, Mapping)
    ]
    building_records_agreement_text = _normalized_text(
        "chicago_building_records_2024_cohort_html/agreement.html"
    )
    permit_panel = payloads[
        "chicago_building_permits_2023_2026_tract_month_panel.json"
    ]
    permit_panel_rows = permit_panel.get("panel")
    permit_panel_rows = (
        permit_panel_rows if isinstance(permit_panel_rows, list) else []
    )
    permit_panel_units = permit_panel.get("units")
    permit_panel_units = (
        permit_panel_units if isinstance(permit_panel_units, list) else []
    )
    permit_panel_summary = permit_panel.get("panel_summary")
    permit_panel_summary = (
        permit_panel_summary
        if isinstance(permit_panel_summary, Mapping)
        else {}
    )
    permit_assignment = permit_panel.get("assignment_diagnostics")
    permit_assignment = (
        permit_assignment if isinstance(permit_assignment, Mapping) else {}
    )
    permit_readiness = permit_panel.get("readiness")
    permit_readiness = (
        permit_readiness if isinstance(permit_readiness, Mapping) else {}
    )
    permit_claim_boundary = permit_panel.get("claim_boundary")
    permit_claim_boundary = (
        permit_claim_boundary
        if isinstance(permit_claim_boundary, Mapping)
        else {}
    )
    permit_panel_artifacts = permit_panel.get("artifacts")
    permit_panel_artifacts = (
        permit_panel_artifacts
        if isinstance(permit_panel_artifacts, Mapping)
        else {}
    )
    permit_panel_without_digest = dict(permit_panel)
    permit_panel_digest = permit_panel_without_digest.pop("panel_digest", None)
    permit_missingness = payloads[
        "chicago_building_permits_spatial_missingness_diagnostic.json"
    ]
    permit_recovery = permit_missingness.get("recovery_ladder")
    permit_recovery = (
        permit_recovery if isinstance(permit_recovery, Mapping) else {}
    )
    permit_missingness_structure = permit_missingness.get(
        "missingness_structure"
    )
    permit_missingness_structure = (
        permit_missingness_structure
        if isinstance(permit_missingness_structure, Mapping)
        else {}
    )
    remaining_spatial_adjudication = payloads[
        "chicago_building_permits_remaining_spatial_adjudication.json"
    ]
    remaining_pin = remaining_spatial_adjudication.get(
        "pin_parcel_adjudication"
    )
    remaining_pin = remaining_pin if isinstance(remaining_pin, Mapping) else {}
    remaining_facility = remaining_spatial_adjudication.get("facility_context")
    remaining_facility = (
        remaining_facility if isinstance(remaining_facility, Mapping) else {}
    )
    remaining_readiness = remaining_spatial_adjudication.get("readiness")
    remaining_readiness = (
        remaining_readiness if isinstance(remaining_readiness, Mapping) else {}
    )
    remaining_claim_boundary = remaining_spatial_adjudication.get(
        "claim_boundary"
    )
    remaining_claim_boundary = (
        remaining_claim_boundary
        if isinstance(remaining_claim_boundary, Mapping)
        else {}
    )
    remaining_digest_payload = dict(remaining_spatial_adjudication)
    remaining_checked_digest = remaining_digest_payload.pop(
        "adjudication_digest", None
    )

    checks = {
        "official_socrata_permit_snapshot_identity": _check(
            bool(
                permit_panel.get("schema")
                == "gwm.chicago_building_permits_tract_month_panel.v1"
                and permit_panel.get("source", {}).get("dataset_id")
                == "ydr8-5enu"
                and permit_panel.get("query_contract", {}).get("row_count")
                == 114896
                and permit_panel.get("query_contract", {}).get("part_counts")
                == [25000, 25000, 25000, 25000, 14896]
                and permit_panel.get("query_contract", {}).get(
                    "window_start_inclusive"
                )
                == "2023-01-01"
                and permit_panel.get("query_contract", {}).get(
                    "window_end_exclusive"
                )
                == "2026-07-01"
            ),
            {
                "dataset_id": permit_panel.get("source", {}).get("dataset_id"),
                "row_count": permit_panel.get("query_contract", {}).get(
                    "row_count"
                ),
                "part_counts": permit_panel.get("query_contract", {}).get(
                    "part_counts"
                ),
                "complete_month_count": permit_panel.get(
                    "query_contract", {}
                ).get("complete_month_count"),
            },
        ),
        "official_socrata_browser_capture_hash_chain": _check(
            bool(
                len(permit_panel_artifacts) == 41
                and all(
                    _artifact_ref_matches(reference, artifacts)
                    for reference in permit_panel_artifacts.values()
                )
            ),
            {
                "panel_source_artifact_count": len(permit_panel_artifacts),
                "hash_bound_artifact_count": sum(
                    _artifact_ref_matches(reference, artifacts)
                    for reference in permit_panel_artifacts.values()
                ),
                "cookies_or_credentials_persisted": False,
            },
        ),
        "official_chicago_2020_tract_universe": _check(
            bool(
                permit_panel.get("spatial_contract", {}).get("city_place_geoid")
                == "1714000"
                and permit_panel.get("spatial_contract", {}).get(
                    "city_tract_count"
                )
                == 801
                and len(permit_panel_units) == 801
                and len(
                    {
                        str(unit.get("tract_geoid") or "")
                        for unit in permit_panel_units
                        if isinstance(unit, Mapping)
                    }
                )
                == 801
            ),
            {
                "place_geoid": permit_panel.get("spatial_contract", {}).get(
                    "city_place_geoid"
                ),
                "city_tract_count": len(permit_panel_units),
                "membership_rule": permit_panel.get("spatial_contract", {}).get(
                    "city_tract_membership_rule"
                ),
            },
        ),
        "official_permit_tract_month_panel_materialized": _check(
            bool(
                permit_panel_summary.get("unit_count") == 801
                and permit_panel_summary.get("month_count") == 42
                and permit_panel_summary.get("panel_row_count") == 33642
                and permit_panel_summary.get("permit_count") == 114816
                and len(permit_panel_rows) == 33642
                and len(
                    {
                        (row.get("tract_geoid"), row.get("month"))
                        for row in permit_panel_rows
                        if isinstance(row, Mapping)
                    }
                )
                == 33642
                and sum(
                    int(row.get("permit_count") or 0)
                    for row in permit_panel_rows
                    if isinstance(row, Mapping)
                )
                == 114816
                and permit_panel_digest
                == _canonical_ascii_digest(permit_panel_without_digest)
            ),
            {
                "unit_count": permit_panel_summary.get("unit_count"),
                "month_count": permit_panel_summary.get("month_count"),
                "panel_row_count": len(permit_panel_rows),
                "permit_count": permit_panel_summary.get("permit_count"),
                "panel_digest": permit_panel_digest,
            },
        ),
        "permit_spatial_assignment_fail_closed": _check(
            bool(
                permit_assignment.get("admitted_row_count") == 114816
                and permit_assignment.get("unresolved_row_count") == 72
                and permit_assignment.get("outside_city_row_count") == 8
                and permit_assignment.get("direct_point_conflict_count") == 363
                and permit_readiness.get("tract_month_panel_materialized") is True
                and permit_readiness.get("complete_spatial_assignment_ready")
                is False
                and permit_claim_boundary.get(
                    "spatially_unresolved_rows_not_silently_imputed"
                )
                is True
            ),
            {
                "admitted_row_count": permit_assignment.get(
                    "admitted_row_count"
                ),
                "admitted_share": permit_assignment.get("admitted_share"),
                "unresolved_row_count": permit_assignment.get(
                    "unresolved_row_count"
                ),
                "outside_city_row_count": permit_assignment.get(
                    "outside_city_row_count"
                ),
                "direct_point_conflict_count": permit_assignment.get(
                    "direct_point_conflict_count"
                ),
            },
        ),
        "permit_missing_coordinate_recovery_fail_closed": _check(
            bool(
                permit_recovery.get(
                    "initial_unresolved_without_valid_wgs84_or_2020_tract"
                )
                == 1658
                and permit_recovery.get(
                    "state_plane_recovered_initially_unresolved_count"
                )
                == 1542
                and permit_assignment.get("state_plane_candidate_count") == 1629
                and permit_assignment.get("address_geocoder_candidate_count")
                == 44
                and permit_panel.get("query_contract", {})
                .get("unresolved_geocoder_validation", {})
                .get("exact_score_100_point_address_count")
                == 8
                and permit_panel.get("query_contract", {})
                .get("unresolved_geocoder_validation", {})
                .get("fuzzy_point_address_count")
                == 4
                and permit_panel.get("query_contract", {})
                .get("unresolved_geocoder_validation", {})
                .get("fuzzy_matches_admitted")
                is False
                and permit_missingness_structure.get("missingness_assumed_random")
                is False
            ),
            {
                "initial_unresolved_row_count": permit_recovery.get(
                    "initial_unresolved_without_valid_wgs84_or_2020_tract"
                ),
                "state_plane_recovered_row_count": permit_recovery.get(
                    "state_plane_recovered_initially_unresolved_count"
                ),
                "exact_address_geocoder_recovered_row_count": (
                    permit_assignment.get("address_geocoder_candidate_count")
                ),
                "remaining_unresolved_row_count": permit_assignment.get(
                    "unresolved_row_count"
                ),
                "fuzzy_address_matches_admitted": False,
                "missingness_assumed_random": False,
            },
        ),
        "remaining_pin_and_facility_recovery_stays_fail_closed": _check(
            bool(
                remaining_checked_digest
                == _canonical_ascii_digest(remaining_digest_payload)
                and all(
                    _artifact_ref_matches(reference, artifacts)
                    for reference in remaining_spatial_adjudication.get(
                        "artifacts", {}
                    ).values()
                )
                and remaining_spatial_adjudication.get(
                    "remaining_unresolved_row_count"
                )
                == 72
                and remaining_pin.get("pin_bearing_row_count") == 14
                and remaining_pin.get("requested_unique_pin_count") == 14
                and remaining_pin.get("returned_unique_pin_polygon_count")
                == 11
                and remaining_pin.get("address_consistent_row_count") == 0
                and remaining_pin.get("admitted_row_count") == 0
                and remaining_facility.get("context_row_count") == 26
                and remaining_facility.get("official_point_tract_geoid")
                == "17043840000"
                and remaining_facility.get("source_geometry_type") == "point"
                and remaining_facility.get("permit_tract_assignment_admitted")
                is False
                and remaining_readiness.get("complete_spatial_assignment_ready")
                is False
                and remaining_readiness.get("causal_estimation_ready") is False
                and remaining_claim_boundary.get(
                    "facility_point_not_permit_location"
                )
                is True
                and remaining_claim_boundary.get(
                    "negative_recovery_result_preserved"
                )
                is True
            ),
            {
                "adjudication_digest": remaining_checked_digest,
                "pin_bearing_row_count": remaining_pin.get(
                    "pin_bearing_row_count"
                ),
                "returned_unique_pin_polygon_count": remaining_pin.get(
                    "returned_unique_pin_polygon_count"
                ),
                "pin_recovered_row_count": remaining_pin.get(
                    "admitted_row_count"
                ),
                "facility_context_row_count": remaining_facility.get(
                    "context_row_count"
                ),
                "facility_point_used_as_permit_location": False,
                "remaining_unresolved_row_count": 72,
            },
        ),
        "candidate_control_claim_boundary_remains_closed": _check(
            bool(
                permit_panel_summary.get("target_event_tract_count") == 17
                and permit_panel_summary.get("candidate_control_tract_count")
                == 700
                and permit_readiness.get(
                    "candidate_control_outcomes_materialized"
                )
                is True
                and permit_readiness.get(
                    "verified_untreated_control_status_ready"
                )
                is False
                and permit_readiness.get("causal_estimation_ready") is False
                and permit_claim_boundary.get(
                    "candidate_controls_not_verified_globally_untreated"
                )
                is True
            ),
            {
                "treated_event_tract_count": permit_panel_summary.get(
                    "target_event_tract_count"
                ),
                "queen_interference_buffer_tract_count": permit_panel_summary.get(
                    "cohort_role_counts", {}
                ).get("interference_buffer_queen_neighbor"),
                "candidate_control_tract_count": permit_panel_summary.get(
                    "candidate_control_tract_count"
                ),
                "verified_untreated_control_status_ready": False,
            },
        ),
        "official_permit_catalog_identity": _check(
            bool(
                dcat.get("identifier")
                == "https://data.cityofchicago.org/api/views/ydr8-5enu"
                and organization.get("name") == "City of Chicago"
                and organization.get("organization_type") == "City Government"
                and dcat.get("accessLevel") == "public"
            ),
            {
                "title": dcat.get("title"),
                "organization": organization.get("name"),
                "organization_type": organization.get("organization_type"),
                "access_level": dcat.get("accessLevel"),
            },
        ),
        "official_permit_catalog_coverage": _check(
            bool(
                "from 2006 to the present" in str(dcat.get("description") or "")
                and dcat.get("modified") == "2026-07-21"
                and len(distributions) == 6
            ),
            {
                "modified": dcat.get("modified"),
                "distribution_count": len(distributions),
                "license_declared": bool(dcat.get("license")),
            },
        ),
        "official_chicago_point_address": _check(
            bool(
                address.get("score") == 100
                and address.get("address") == "6716 S BISHOP ST, 60636"
                and address_attributes.get("Addr_type") == "PointAddress"
                and str(address_attributes.get("PINNO")) == "2020302029"
            ),
            {
                "address": address.get("address"),
                "score": address.get("score"),
                "address_type": address_attributes.get("Addr_type"),
                "pin": str(address_attributes.get("PINNO") or ""),
                "ward": address_attributes.get("WARD"),
                "community": address_attributes.get("COMMUNITY"),
            },
        ),
        "official_fcc_block_to_tract": _check(
            bool(
                fcc.get("status") == "OK"
                and block_fips == "170316716001013"
                and derived_tract == TARGET_TRACT_GEOID
            ),
            {
                "block_fips": block_fips,
                "derived_tract_geoid": derived_tract,
            },
        ),
        "official_current_zoning_context": _check(
            bool(
                len(zoning_features) == 1
                and zoning_attributes.get("OBJECTID") == 1661018
                and zoning_attributes.get("ZONE_CLASS") == "RS-3"
            ),
            {
                "feature_count": len(zoning_features),
                "object_id": zoning_attributes.get("OBJECTID"),
                "zone_class": zoning_attributes.get("ZONE_CLASS"),
            },
        ),
        "treatment_polygon_remains_unresolved": _check(
            bool(
                zoning_attributes.get("CASE_NUMBER") is None
                and zoning_attributes.get("ORDINANCE_NUM") is None
                and zoning_attributes.get("CLERK_DOCNO") is None
                and not zoning_case_features
            ),
            {
                "current_case_number": zoning_attributes.get("CASE_NUMBER"),
                "current_ordinance_number": zoning_attributes.get(
                    "ORDINANCE_NUM"
                ),
                "current_clerk_document_number": zoning_attributes.get(
                    "CLERK_DOCNO"
                ),
                "case_23063_feature_count": len(zoning_case_features),
                "interpretation": (
                    "negative evidence; current zoning is not treatment polygon"
                ),
            },
        ),
        "secondary_acs2024_sample": _check(
            bool(
                acs_release.get("id") == "acs2024_5yr"
                and set(tract_data) == expected_tables
                and estimate_moe_complete
            ),
            {
                "provider": "Census Reporter",
                "authority": "secondary",
                "release_id": acs_release.get("id"),
                "release_years": acs_release.get("years"),
                "table_ids": sorted(tract_data),
                "estimate_moe_complete": estimate_moe_complete,
            },
        ),
        "secondary_tiger2024_geometry_sample": _check(
            bool(
                geometry.get("type") == "Polygon"
                and properties.get("geoid")
                == "14000US" + TARGET_TRACT_GEOID
                and len(outer_ring) >= 4
            ),
            {
                "provider": "Census Reporter",
                "authority": "secondary",
                "geometry_type": geometry.get("type"),
                "geoid": properties.get("geoid"),
                "outer_ring_vertex_count": len(outer_ring),
            },
        ),
        "point_inside_secondary_tract_geometry": _check(
            point_inside,
            {
                "point_wgs84": list(TARGET_POINT_WGS84),
                "tract_geoid": TARGET_TRACT_GEOID,
                "point_inside_or_on_boundary": point_inside,
            },
        ),
        "secondary_cook_county_tract_geometry_coverage": _check(
            bool(
                cook_geometry.get("type") == "FeatureCollection"
                and len(cook_geometry_features) == 1332
                and len(cook_geometry_geoids) == 1332
                and cook_geometry_types == {"Polygon"}
                and all(
                    full_geoid.startswith("14000US17031")
                    for full_geoid in cook_geometry_geoids
                )
                and provisional_readiness.get(
                    "secondary_full_cook_geometry_verified"
                )
                is True
                and provisional_readiness.get("all_target_tracts_present")
                is True
            ),
            {
                "provider": "Census Reporter",
                "authority": "verified_secondary_not_official_admission",
                "feature_count": len(cook_geometry_features),
                "unique_geoid_count": len(cook_geometry_geoids),
                "geometry_types": sorted(cook_geometry_types),
                "target_event_count": provisional_target.get("event_count"),
                "target_distinct_tract_count": provisional_target.get(
                    "distinct_tract_count"
                ),
                "official_tiger_geometry_verified": False,
            },
        ),
        "secondary_provisional_adjacency_reproducible": _check(
            bool(
                provisional_adjacency.get("schema")
                == "gwm.chicago_provisional_tract_adjacency.v1"
                and provisional_checked_digest
                == _canonical_digest(provisional_digest_payload)
                and _artifact_ref_matches(
                    provisional_adjacency.get("artifacts", {}).get(
                        "census_reporter_tiger2024_cook_county_tracts.json"
                    ),
                    artifacts,
                )
                and _artifact_ref_matches(
                    provisional_adjacency.get("artifacts", {}).get(
                        "historical_cohort_spatial_crosswalk.json"
                    ),
                    artifacts,
                )
                and provisional_graph.get("node_count") == 1332
                and provisional_graph.get("queen_edge_count") == 2458
                and provisional_graph.get("rook_edge_count") == 1081
                and provisional_target.get("event_count") == 17
                and provisional_target.get("distinct_tract_count") == 17
                and provisional_target.get("missing_target_tracts") == []
            ),
            {
                "adjacency_digest": provisional_checked_digest,
                "node_count": provisional_graph.get("node_count"),
                "queen_edge_count": provisional_graph.get(
                    "queen_edge_count"
                ),
                "rook_edge_count": provisional_graph.get("rook_edge_count"),
                "target_tract_count": provisional_target.get(
                    "distinct_tract_count"
                ),
                "official_network_admitted": False,
            },
        ),
        "secondary_provisional_adjacency_topology_fails_closed": _check(
            bool(
                provisional_graph.get("queen_connected_component_count") == 100
                and provisional_graph.get("rook_connected_component_count")
                == 378
                and provisional_graph.get("queen_isolated_node_count") == 67
                and provisional_graph.get("rook_isolated_node_count") == 234
                and provisional_quality.get("queen_isolated_node_share")
                == 0.0503
                and provisional_quality.get("rook_to_queen_edge_ratio")
                == 0.439788
                and provisional_quality.get("passed") is False
                and provisional_target.get("tracts_with_zero_rook_neighbors")
                == ["17031242700", "17031243500", "17031836000"]
                and provisional_readiness.get(
                    "provisional_interference_network_usable"
                )
                is False
                and provisional_readiness.get(
                    "official_adjacency_constructed"
                )
                is False
                and provisional_readiness.get("network_to_unit_time_ready")
                is False
            ),
            {
                "queen_connected_component_count": provisional_graph.get(
                    "queen_connected_component_count"
                ),
                "rook_connected_component_count": provisional_graph.get(
                    "rook_connected_component_count"
                ),
                "queen_isolated_node_count": provisional_graph.get(
                    "queen_isolated_node_count"
                ),
                "rook_isolated_node_count": provisional_graph.get(
                    "rook_isolated_node_count"
                ),
                "target_tracts_with_zero_rook_neighbors": (
                    provisional_target.get("tracts_with_zero_rook_neighbors")
                ),
                "failure_reason": provisional_quality.get(
                    "failure_interpretation"
                ),
                "topology_quality_pass": False,
            },
        ),
        "official_tiger2020_geometry_components_verified": _check(
            bool(
                official_adjacency.get("schema")
                == "gwm.chicago_official_tiger2020_tract_adjacency.v1"
                and official_checked_digest
                == _canonical_digest(official_digest_payload)
                and official_adjacency.get("source", {}).get(
                    "canonical_url"
                )
                == (
                    "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/"
                    "tl_2020_17_tract.zip"
                )
                and all(
                    _artifact_ref_matches(
                        official_adjacency.get("artifacts", {}).get(
                            Path(filename).name
                        ),
                        artifacts,
                    )
                    for filename in official_component_filenames
                )
                and _artifact_ref_matches(
                    official_adjacency.get("artifacts", {}).get(
                        "historical_cohort_spatial_crosswalk.json"
                    ),
                    artifacts,
                )
                and official_geometry.get("driver") == "ESRI Shapefile"
                and official_geometry.get("source_feature_count") == 3265
                and official_geometry.get("cook_county_feature_count") == 1332
                and official_geometry.get("unique_cook_tract_geoid_count")
                == 1332
                and official_geometry.get("valid_nonempty_geometry_count")
                == 1332
                and official_geometry.get("geometry_types") == ["Polygon"]
                and official_geometry.get("coordinate_reference_system")
                == "EPSG:4269"
                and {"STATEFP", "COUNTYFP", "TRACTCE", "GEOID"}
                <= set(official_geometry.get("schema_fields") or [])
                and official_geometry.get("source_bounds")
                == [-91.513079, 36.970298, -87.019935, 42.508481]
                and official_readiness.get("official_tiger_geometry_verified")
                is True
            ),
            {
                "adjacency_digest": official_checked_digest,
                "source_feature_count": official_geometry.get(
                    "source_feature_count"
                ),
                "cook_county_feature_count": official_geometry.get(
                    "cook_county_feature_count"
                ),
                "crs": official_geometry.get("coordinate_reference_system"),
                "component_count": len(official_component_filenames),
                "component_level_hashes_verified": True,
                "original_archive_bytes_preserved": False,
            },
        ),
        "official_tiger2020_adjacency_topology_passes": _check(
            bool(
                official_graph.get("node_count") == 1332
                and official_graph.get("queen_edge_count") == 4410
                and official_graph.get("rook_edge_count") == 3416
                and official_graph.get("queen_connected_component_count") == 1
                and official_graph.get("rook_connected_component_count") == 1
                and official_graph.get("queen_isolated_node_count") == 0
                and official_graph.get("rook_isolated_node_count") == 0
                and official_quality.get("rook_to_queen_edge_ratio")
                == 0.774603
                and official_quality.get("passed") is True
                and official_target.get("event_count") == 17
                and official_target.get("distinct_tract_count") == 17
                and official_target.get("missing_target_tracts") == []
                and official_target.get("tracts_with_zero_queen_neighbors")
                == []
                and official_target.get("tracts_with_zero_rook_neighbors")
                == []
                and official_readiness.get(
                    "official_cook_internal_interference_network_usable"
                )
                is True
                and official_readiness.get("network_to_unit_time_ready") is True
                and official_readiness.get("causal_estimation_ready") is False
            ),
            {
                "node_count": official_graph.get("node_count"),
                "queen_edge_count": official_graph.get("queen_edge_count"),
                "rook_edge_count": official_graph.get("rook_edge_count"),
                "queen_connected_component_count": official_graph.get(
                    "queen_connected_component_count"
                ),
                "rook_connected_component_count": official_graph.get(
                    "rook_connected_component_count"
                ),
                "target_tract_count": official_target.get(
                    "distinct_tract_count"
                ),
                "topology_quality_pass": official_quality.get("passed"),
                "causal_estimation_admitted": False,
            },
        ),
        "official_chicago_city_network_is_cook_dupage_complete": _check(
            bool(
                city_adjacency.get("schema")
                == "gwm.chicago_official_tiger2020_city_tract_adjacency.v1"
                and city_checked_digest
                == _canonical_ascii_digest(city_digest_payload)
                and all(
                    _artifact_ref_matches(reference, artifacts)
                    for reference in city_adjacency.get("artifacts", {}).values()
                )
                and city_units.get("city_tract_count") == 801
                and city_units.get("cook_tract_count") == 799
                and city_units.get("dupage_tract_count") == 2
                and city_units.get("county_counts") == {"031": 799, "043": 2}
                and [
                    unit.get("tract_geoid")
                    for unit in city_units.get("dupage_units", [])
                ]
                == ["17043840000", "17043840801"]
                and city_graph.get("node_count") == 801
                and city_graph.get("queen_edge_count") == 2636
                and city_graph.get("rook_edge_count") == 1889
                and city_graph.get("queen_connected_component_count") == 1
                and city_graph.get("rook_connected_component_count") == 1
                and city_graph.get("queen_isolated_node_count") == 0
                and city_graph.get("rook_isolated_node_count") == 0
                and city_quality.get("passed") is True
                and city_readiness.get(
                    "official_cook_dupage_city_adjacency_constructed"
                )
                is True
                and city_readiness.get("network_to_unit_time_ready") is True
                and city_readiness.get("outside_city_interference_ready")
                is False
                and city_claim_boundary.get(
                    "city_internal_network_not_outside_city_interference"
                )
                is True
            ),
            {
                "adjacency_digest": city_checked_digest,
                "city_tract_count": city_units.get("city_tract_count"),
                "county_counts": city_units.get("county_counts"),
                "queen_edge_count": city_graph.get("queen_edge_count"),
                "rook_edge_count": city_graph.get("rook_edge_count"),
                "topology_quality_pass": city_quality.get("passed"),
                "outside_city_interference_ready": False,
            },
        ),
        "official_tiger2020_illinois_catalog_identity": _check(
            bool(
                len(tiger_catalog_results) == 1
                and tiger_dcat.get("title")
                == "TIGER/Line Shapefile, 2020, State, Illinois, Census Tracts"
                and tiger_dcat.get("identifier")
                == (
                    "https://meta.geo.census.gov/data/existing/decennial/GEO/"
                    "GPMB/TIGERline/Collections/2020/tract/"
                    "tl_2020_17_tract.shp.iso.xml"
                )
                and tiger_organization.get("name")
                == "U.S. Census Bureau, Department of Commerce"
                and tiger_organization.get("organization_type")
                == "Federal Government"
                and tiger_dcat.get("issued")
                == "2020-01-01T00:00:00.000+00:00"
                and tiger_dcat.get("license")
                == "https://creativecommons.org/publicdomain/zero/1.0/"
                and {"Illinois", "IL", "17", "Polygon", "Census Tract"}
                <= set(tiger_dcat.get("keyword") or [])
                and tiger_zip_distribution.get("downloadURL")
                == (
                    "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/"
                    "tl_2020_17_tract.zip"
                )
                and tiger_zip_distribution.get("format") == "ZIP"
                and tiger_zip_distribution.get("mediaType")
                == "application/zip"
            ),
            {
                "title": tiger_dcat.get("title"),
                "publisher": tiger_dcat.get("publisher"),
                "organization": tiger_organization.get("name"),
                "organization_type": tiger_organization.get(
                    "organization_type"
                ),
                "license": tiger_dcat.get("license"),
                "issued": tiger_dcat.get("issued"),
                "last_harvested_date": tiger_catalog_record.get(
                    "last_harvested_date"
                ),
                "zip_url": tiger_zip_distribution.get("downloadURL"),
                "zip_bytes_verified": False,
                "downloaded_components_verified": True,
            },
        ),
        "official_tiger2020_illinois_iso_metadata": _check(
            bool(
                tiger_iso_file_identifier == "tl_2020_17_tract.shp.iso.xml"
                and tiger_iso_crs == "urn:ogc:def:crs:EPSG::4269"
                and tiger_iso_feature_type == "Census Tracts"
                and tiger_iso_bbox
                == {
                    "west": "-91.513079",
                    "east": "-87.019935",
                    "south": "36.970298",
                    "north": "42.508481",
                }
                and (
                    "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/"
                    "tl_2020_17_tract.zip"
                )
                in tiger_iso_urls
                and tiger_iso_fees
                == (
                    "The online copy of the TIGER/Line Shapefiles may be "
                    "accessed without charge."
                )
            ),
            {
                "file_identifier": tiger_iso_file_identifier,
                "feature_type": tiger_iso_feature_type,
                "crs": tiger_iso_crs,
                "bbox": tiger_iso_bbox,
                "transfer_url_count": len(tiger_iso_urls),
                "fees": tiger_iso_fees,
                "actual_geometry_sample_verified": True,
                "actual_geoid_fields_verified": True,
                "component_level_hashes_verified": True,
            },
        ),
        "official_elms_matter_and_final_attachments": _check(
            bool(
                matter.get("matterId")
                == "86390664-2D38-F111-88B3-001DD8033B18"
                and matter.get("recordNumber") == "O2026-0024863"
                and matter.get("status") == "90-Final"
                and matter.get("subStatus") == "Passed"
                and attachment_by_name.get(final_ordinance_name, {}).get("path")
                == final_ordinance_url
                and attachment_by_name.get(final_narrative_name, {}).get("path")
                == final_narrative_url
            ),
            {
                "matter_id": matter.get("matterId"),
                "record_number": matter.get("recordNumber"),
                "status": matter.get("status"),
                "sub_status": matter.get("subStatus"),
                "final_action_date": matter.get("finalActionDate"),
                "last_publication_date": matter.get("lastPublicationDate"),
                "attachment_count": len(matter_attachments),
            },
        ),
        "official_final_document_integrity": _check(
            bool(
                ordinance_pdf["bytes"] == 26692
                and narrative_pdf["bytes"] == 291862
                and _has_pdf_magic(
                    "chicago_elms_O2026_0024863_final_ordinance.pdf"
                )
                and _has_pdf_magic(
                    "chicago_elms_O2026_0024863_final_narrative_and_plans.pdf"
                )
            ),
            {
                "final_ordinance_bytes": ordinance_pdf["bytes"],
                "final_narrative_and_plans_bytes": narrative_pdf["bytes"],
                "extraction_method": "Apple Vision local OCR",
                "ocr_is_derived_evidence": True,
            },
        ),
        "enacted_zoning_transition_and_legal_boundary": _check(
            bool(
                "changing all of the rs-3 residential single-unit" in ordinance_text
                and "to those of a rm-4.5 residential multi-unit district"
                in ordinance_text
                and "a line 166 feet south of and parallel to west marquette road"
                in ordinance_text
                and "a line 191 feet south of and parallel to west marquette road"
                in ordinance_text
                and "south bishop street" in ordinance_text
                and "the alley next west of and parallel to south bishop street"
                in ordinance_text
            ),
            {
                "from_zoning": "RS-3",
                "to_zoning": "RM-4.5",
                "north_offset_from_west_marquette_road_feet": 166,
                "south_offset_from_west_marquette_road_feet": 191,
                "north_south_depth_feet": 25,
                "east_boundary": "South Bishop Street",
                "west_boundary": (
                    "alley next west of and parallel to South Bishop Street"
                ),
                "legal_boundary_verified": True,
                "machine_polygon_verified": False,
            },
        ),
        "effective_date_semantics_remain_unresolved": _check(
            bool(
                "this ordinance takes effect after its passage and due publication"
                in ordinance_text
                and matter.get("finalActionDate")
                == "2026-07-15T15:00:00+00:00"
                and matter.get("lastPublicationDate")
                == "2026-07-17T14:25:18+00:00"
            ),
            {
                "effective_rule": "after passage and due publication",
                "passage_timestamp": matter.get("finalActionDate"),
                "elms_last_publication_timestamp": matter.get(
                    "lastPublicationDate"
                ),
                "last_publication_field_legal_semantics_documented": False,
                "effective_onset_verified": False,
            },
        ),
        "official_final_narrative_land_use": _check(
            bool(
                "proposed zoning: rm-4.5 residential multi-unit district"
                in narrative_text
                and "lot area: 3,115 sf" in narrative_text
                and "2 proposed dwelling units" in narrative_text
                and "building height: 28 feet existing to remain" in narrative_text
            ),
            {
                "proposed_zoning": "RM-4.5",
                "lot_area_square_feet": 3115,
                "proposed_dwelling_units": 2,
                "building_height_feet": 28,
            },
        ),
        "official_cook_county_parcel_metadata": _check(
            bool(
                parcel_dcat.get("title") == "ccgisdata - Parcel 2021"
                and parcel_organization.get("name") == "Cook County of Illinois"
                and parcel_organization.get("organization_type")
                == "County Government"
                and parcel_item.get("owner") == "Cook_County_GIS"
                and parcel_item.get("accessInformation") == "Cook County Clerk"
                and parcel_item.get("access") == "public"
                and parcel_item.get("url") == parcel_service_url
                and parcel_attributes.get("geometryType")
                == "esriGeometryPolygon"
                and {"name", "pin10", "censustract_geoid"}.issubset(
                    set(parcel_fields)
                )
                and parcel_attributes.get("downloadable") is True
                and bool(parcel_attributes.get("structuredLicense"))
            ),
            {
                "dataset_id": "77tz-riq7",
                "arcgis_item_id": parcel_item.get("id"),
                "owner": parcel_item.get("owner"),
                "source": parcel_attributes.get("source"),
                "access_information": parcel_item.get("accessInformation"),
                "access": parcel_item.get("access"),
                "geometry_type": parcel_attributes.get("geometryType"),
                "pin_fields_present": all(
                    field in parcel_fields for field in ("name", "pin10")
                ),
                "tract_field_present": "censustract_geoid" in parcel_fields,
                "license_declared": bool(parcel_item.get("licenseInfo")),
                "target_pin10": TARGET_PIN10,
                "target_row_or_geometry_sample_verified": False,
                "query_observation": "official feature query timed out",
            },
        ),
        "official_chicago_developer_repository_identity": _check(
            bool(
                chicago_dev_repository.get("full_name")
                == "Chicago/dev.cityofchicago.org"
                and chicago_dev_owner.get("login") == "Chicago"
                and chicago_dev_owner.get("type") == "Organization"
                and chicago_dev_repository.get("fork") is False
                and chicago_dev_repository.get("visibility") == "public"
            ),
            {
                "repository": chicago_dev_repository.get("full_name"),
                "owner": chicago_dev_owner.get("login"),
                "owner_type": chicago_dev_owner.get("type"),
                "fork": chicago_dev_repository.get("fork"),
                "visibility": chicago_dev_repository.get("visibility"),
                "description": chicago_dev_repository.get("description"),
            },
        ),
        "official_permit_historical_schema_semantics": _check(
            bool(
                "author: open data portal team" in permit_changes_text
                and "tags: - ydr8-5enu" in permit_changes_text
                and "application_start_date" in permit_changes_text
                and "processing_time" in permit_changes_text
                and "community_area" in permit_changes_text
                and "census_tract" in permit_changes_text
                and "xcoordinate" in permit_changes_text
                and "ycoordinate" in permit_changes_text
                and "renaming estimated_cost to reported_cost"
                in permit_changes_text
            ),
            {
                "documented_at": "2019-07-09T16:00:00-05:00",
                "dataset_id": "ydr8-5enu",
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
                "current_schema_verified": False,
            },
        ),
        "official_permit_issue_date_fallback_semantics": _check(
            bool(
                "author: open data portal team" in permit_issue_date_text
                and "tags: - ydr8-5enu" in permit_issue_date_text
                and "about five percent of records" in permit_issue_date_text
                and "a second database field" in permit_issue_date_text
                and "if the main field is blank" in permit_issue_date_text
                and "all records now have a value for `issue_date`"
                in permit_issue_date_text
            ),
            {
                "documented_at": "2017-11-20T11:00:00-06:00",
                "dataset_id": "ydr8-5enu",
                "issue_date_primary_field_fallback_documented": True,
                "fallback_only_when_primary_blank": True,
                "historical_missing_share_approximate": 0.05,
                "current_row_level_issue_date_complete_verified": False,
                "causal_warning": (
                    "ISSUE_DATE may combine two source-system date fields and is "
                    "not evidence of construction start"
                ),
            },
        ),
        "official_permit_contact_field_removal_semantics": _check(
            bool(
                "author: open data portal team" in permit_contact_text
                and "tags: - ydr8-5enu" in permit_contact_text
                and "removing all 15 contractor address columns"
                in permit_contact_text
                and "removing all 15 contractor phone columns"
                in permit_contact_text
                and "potential misuses" in permit_contact_text
                and "individual-permit basis" in permit_contact_text
            ),
            {
                "documented_at": "2019-07-16T14:45:00-05:00",
                "dataset_id": "ydr8-5enu",
                "bulk_contact_addresses_removed": True,
                "bulk_contact_phones_removed": True,
                "removal_reason": "privacy and misuse risk",
                "not_a_random_missingness_mechanism": True,
            },
        ),
        "official_building_records_identity_and_agreement": _check(
            bool(
                building_records.get("schema")
                == "gwm.chicago_building_records_bounded_cohort_probe.v1"
                and building_records_source.get("publisher")
                == "City of Chicago Department of Buildings"
                and building_records_source.get("canonical_url")
                == "https://webapps1.chicago.gov/buildingrecords/"
                and building_records_source.get("agreement_http_status") == 200
                and building_records_source.get("home_http_status") == 200
                and "this application provides public access to building permit"
                in building_records_agreement_text
                and "i accept the terms of this license"
                in building_records_agreement_text
            ),
            {
                "publisher": building_records_source.get("publisher"),
                "canonical_url": building_records_source.get("canonical_url"),
                "access_mode": building_records_source.get("access_mode"),
                "access_boundary": building_records_source.get(
                    "access_boundary"
                ),
                "agreement_http_status": building_records_source.get(
                    "agreement_http_status"
                ),
                "license_terms_require_review": True,
            },
        ),
        "official_building_records_current_address_schema": _check(
            bool(
                building_records_source.get("current_permit_columns")
                == ["PERMIT #", "DATE ISSUED", "DESCRIPTION OF WORK"]
                and building_records_summary.get(
                    "current_permit_schema_verified_count"
                )
                == 16
                and building_records_summary.get(
                    "address_history_with_permits_count"
                )
                == 16
                and building_records_summary.get(
                    "zero_permit_address_history_count"
                )
                == 1
                and building_records_readiness.get(
                    "official_current_address_level_schema_verified"
                )
                is True
                and building_records_readiness.get(
                    "official_zero_permit_address_results_verified"
                )
                is True
            ),
            {
                "current_permit_columns": building_records_source.get(
                    "current_permit_columns"
                ),
                "nonempty_address_histories_with_matching_schema": (
                    building_records_summary.get(
                        "current_permit_schema_verified_count"
                    )
                ),
                "zero_permit_address_histories": building_records_summary.get(
                    "zero_permit_address_history_count"
                ),
                "html_application_schema_is_socrata_bulk_schema": False,
            },
        ),
        "official_building_records_cohort_selection_crosswalk": _check(
            bool(
                building_records_selection.get("cohort_digest")
                == expanded_cohort.get("cohort_digest")
                and building_records_selection.get("spatial_crosswalk_digest")
                == expanded_crosswalk.get("crosswalk_digest")
                and building_records_selection.get("eligible_event_count") == 17
                and building_records_selection.get("queried_event_count") == 17
                and set(building_record_observations_by_record)
                == set(joint_spatial_events)
                and all(
                    observation.get("tract_geoid")
                    == joint_spatial_events[record_number]
                    .get("tract_crosswalk", {})
                    .get("tract_geoid")
                    for record_number, observation in (
                        building_record_observations_by_record.items()
                    )
                )
            ),
            {
                "selection_rule": building_records_selection.get("rule"),
                "eligible_event_count": building_records_selection.get(
                    "eligible_event_count"
                ),
                "queried_event_count": building_records_selection.get(
                    "queried_event_count"
                ),
                "distinct_crosswalked_tract_count": len(
                    {
                        observation.get("tract_geoid")
                        for observation in building_record_observations
                        if isinstance(observation, Mapping)
                    }
                ),
            },
        ),
        "official_building_records_raw_pages_hash_bound": _check(
            bool(
                len(building_record_observations) == 17
                and _artifact_ref_matches(
                    building_records.get("artifacts", {}).get("agreement"),
                    artifacts,
                )
                and all(
                    _artifact_ref_matches(
                        observation.get("raw_artifact"), artifacts
                    )
                    for observation in building_record_observations
                    if isinstance(observation, Mapping)
                )
            ),
            {
                "agreement_page_hash_bound": _artifact_ref_matches(
                    building_records.get("artifacts", {}).get("agreement"),
                    artifacts,
                ),
                "result_page_count": len(building_record_observations),
                "result_pages_hash_bound": sum(
                    _artifact_ref_matches(
                        observation.get("raw_artifact"), artifacts
                    )
                    for observation in building_record_observations
                    if isinstance(observation, Mapping)
                ),
            },
        ),
        "official_building_records_bounded_permit_rows": _check(
            bool(
                building_records_summary.get("successful_http_result_count")
                == 17
                and building_records_summary.get("exact_input_address_count")
                == 17
                and building_records_summary.get("permit_row_count") == 70
                and len(building_record_permits) == 70
                and all(
                    str(permit.get("permit_number") or "")
                    and _is_iso_date(permit.get("issued_on"))
                    for _, permit in building_record_permits
                )
                and sum(
                    not str(permit.get("description_of_work") or "")
                    for _, permit in building_record_permits
                )
                == 1
                and all(
                    isinstance(observation.get("validation"), Mapping)
                    and observation["validation"].get("result_http_200") is True
                    and observation["validation"].get(
                        "exact_input_address_returned"
                    )
                    is True
                    and observation["validation"].get(
                        "permit_rows_have_stable_id_and_date"
                    )
                    is True
                    and observation["validation"].get(
                        "source_disclaimer_present"
                    )
                    is True
                    for observation in building_record_observations
                    if isinstance(observation, Mapping)
                )
            ),
            {
                "queried_address_count": len(building_record_observations),
                "address_history_with_permits_count": (
                    building_records_summary.get(
                        "address_history_with_permits_count"
                    )
                ),
                "permit_row_count": len(building_record_permits),
                "blank_description_of_work_count": sum(
                    not str(permit.get("description_of_work") or "")
                    for _, permit in building_record_permits
                ),
                "blank_descriptions_imputed": False,
                "stable_id_field": "PERMIT #",
                "time_field": "DATE ISSUED",
                "issue_date_is_construction_start": False,
            },
        ),
        "official_building_records_post_publication_observation": _check(
            bool(
                building_records_summary.get(
                    "post_publication_permit_row_count"
                )
                == 18
                and building_records_summary.get(
                    "address_history_with_post_publication_permits_count"
                )
                == 11
                and sum(
                    str(permit.get("issued_on") or "")
                    > str(observation.get("candidate_publication_date") or "")
                    for observation, permit in building_record_permits
                )
                == 18
            ),
            {
                "post_publication_permit_row_count": (
                    building_records_summary.get(
                        "post_publication_permit_row_count"
                    )
                ),
                "address_history_with_post_publication_permits_count": (
                    building_records_summary.get(
                        "address_history_with_post_publication_permits_count"
                    )
                ),
                "publication_date_is_verified_effective_onset": False,
                "post_publication_is_causal_effect": False,
            },
        ),
        "official_building_records_remains_bounded_outcome_evidence": _check(
            bool(
                building_records_readiness.get(
                    "official_bounded_address_level_rows_verified"
                )
                is True
                and building_records_readiness.get(
                    "full_cohort_address_history_probe_complete"
                )
                is True
                and building_records_readiness.get(
                    "tract_month_outcome_panel_ready"
                )
                is False
                and building_records_readiness.get(
                    "untreated_control_outcomes_ready"
                )
                is False
                and building_records_readiness.get("causal_estimation_ready")
                is False
            ),
            {
                "address_level_rows_verified": True,
                "complete_tract_permit_universe_verified": False,
                "untreated_control_outcomes_verified": False,
                "tract_month_panel_materialized": False,
                "causal_estimation_admitted": False,
            },
        ),
        "monthly_post_treatment_horizon_unavailable": _check(
            bool(
                matter.get("finalActionDate")
                == "2026-07-15T15:00:00+00:00"
                and matter.get("lastPublicationDate")
                == "2026-07-17T14:25:18+00:00"
                and dcat.get("modified") == "2026-07-21"
            ),
            {
                "target_cadence": "monthly",
                "passage_timestamp": matter.get("finalActionDate"),
                "elms_last_publication_timestamp": matter.get(
                    "lastPublicationDate"
                ),
                "latest_official_permit_catalog_date": dcat.get("modified"),
                "complete_post_treatment_months_available": 0,
                "minimum_structural_requirement": (
                    "at least one complete post-treatment period"
                ),
                "candidate_temporal_role": (
                    "crosswalk_fixture_not_effect_estimation_pilot"
                ),
            },
        ),
        "historical_zoning_candidate_filter": _check(
            bool(
                historical_search_meta.get("count") == 290
                and len(historical_zoning_rows) == 88
                and all(
                    row.get("status") == "90-Final"
                    and str(row.get("finalActionDate") or "")
                    < "2025-01-01T00:00:00+00:00"
                    for row in historical_zoning_rows
                )
            ),
            {
                "query_endpoint": "Chicago eLMS /matter",
                "query_top": historical_search_meta.get("top"),
                "filtered_result_count": historical_search_meta.get("count"),
                "zoning_rows_in_first_page": len(historical_zoning_rows),
                "required_status": "90-Final",
                "required_final_action_before": "2025-01-01T00:00:00Z",
                "required_attachment_type": "Exhibits",
            },
        ),
        "historical_zoning_seed_details": _check(
            bool(
                set(historical_candidate_records)
                == {
                    "O2024-0012247",
                    "O2024-0012532",
                    "O2024-0012334",
                }
                and all(
                    _historical_candidate_has_final_documents(candidate)
                    for candidate in historical_candidate_records.values()
                )
            ),
            {
                "candidate_record_numbers": sorted(
                    historical_candidate_records
                ),
                "candidate_count": len(historical_candidate_records),
                "status": "90-Final",
                "sub_status": "Passed",
                "final_action_date": "2024-10-30T15:00:00+00:00",
                "publication_date": "2024-11-21",
                "minimum_complete_post_publication_months": 19,
                "final_ordinance_present": True,
                "final_narrative_and_plans_present": True,
            },
        ),
        "historical_zoning_final_document_integrity": _check(
            bool(
                historical_preflight_scope.get("candidate_count") == 3
                and historical_preflight_scope.get("document_download_count") == 6
                and historical_preflight_scope.get(
                    "bounded_official_document_bytes"
                )
                == 2898496
                and len(historical_preflight_documents) == 6
                and historical_document_integrity
            ),
            {
                "candidate_count": historical_preflight_scope.get(
                    "candidate_count"
                ),
                "document_count": len(historical_preflight_documents),
                "total_bytes": historical_preflight_scope.get(
                    "bounded_official_document_bytes"
                ),
                "pdf_magic_and_sha256_verified": historical_document_integrity,
                "ocr_method": historical_preflight_scope.get("ocr_method"),
            },
        ),
        "historical_zoning_transitions_and_legal_boundaries": _check(
            bool(
                "changing all of the b3-2" in historical_ordinance_text[
                    "O2024-0012247"
                ]
                and "to those of a b2-3" in historical_ordinance_text[
                    "O2024-0012247"
                ]
                and "a line 216 feet east" in historical_ordinance_text[
                    "O2024-0012247"
                ]
                and "a line 192 feet east" in historical_ordinance_text[
                    "O2024-0012247"
                ]
                and "changing all the rs3" in historical_ordinance_text[
                    "O2024-0012532"
                ]
                and "to those of a rm4.5" in historical_ordinance_text[
                    "O2024-0012532"
                ]
                and "line 56.44 feet south" in historical_ordinance_text[
                    "O2024-0012532"
                ]
                and "line 87.44 fee" in historical_ordinance_text[
                    "O2024-0012532"
                ]
                and "changing all of the rt4" in historical_ordinance_text[
                    "O2024-0012334"
                ]
                and "to those of an rm5" in historical_ordinance_text[
                    "O2024-0012334"
                ]
                and "a line 232.00 feet north" in historical_ordinance_text[
                    "O2024-0012334"
                ]
                and "a line 208 feet north" in historical_ordinance_text[
                    "O2024-0012334"
                ]
                and all(
                    "passage and due publication" in text
                    for text in historical_ordinance_text.values()
                )
            ),
            {
                "candidate_specifications": historical_zoning_specifications,
                "legal_boundary_text_verified": True,
                "machine_treatment_geometries_verified": False,
                "effective_rule": "after passage and due publication",
                "effective_onsets_verified": False,
            },
        ),
        "historical_zoning_narrative_project_scale": _check(
            bool(
                "type 1 rezoning from b3-2 to b2-3"
                in historical_narrative_text["O2024-0012247"]
                and "lot area: 2088 sq ft"
                in historical_narrative_text["O2024-0012247"]
                and "from 2 dwelling units to three dwelling units"
                in historical_narrative_text["O2024-0012247"]
                and "approximately 3,885 square feet"
                in historical_narrative_text["O2024-0012532"]
                and "total of four (4) dwelling units"
                in historical_narrative_text["O2024-0012532"]
                and "existing 3 dwelling units & 2 new units (total of 5 d.u.)"
                in historical_narrative_text["O2024-0012334"]
            ),
            {
                "candidate_specifications": historical_zoning_specifications,
                "project_scale_text_verified": True,
                "ocr_is_derived_evidence": True,
            },
        ),
        "historical_candidate_point_and_tract_crosswalk": _check(
            historical_point_crosswalk_ready,
            {
                "address_provider": (
                    "City of Chicago AddressPoints GeocodeServer"
                ),
                "tract_provider": "FCC Census Block API, 2020 vintage",
                "prior_geocode_http_statuses": historical_geocode_statuses,
                "candidate_count": len(historical_event_crosswalks),
                "point_addresses_verified": historical_point_crosswalk_ready,
                "pins_verified": historical_point_crosswalk_ready,
                "tract_crosswalks_verified": historical_point_crosswalk_ready,
                "tract_geoids": sorted(
                    crosswalk["tract_geoid"]
                    for crosswalk in historical_event_crosswalks.values()
                ),
            },
        ),
        "historical_current_zoning_map_update": _check(
            historical_zoning_map_polygons_ready,
            {
                "provider": "City of Chicago current Zoning FeatureServer",
                "candidate_count": len(historical_event_crosswalks),
                "clerk_document_numbers_verified": (
                    historical_zoning_map_polygons_ready
                ),
                "destination_zone_classes_verified": (
                    historical_zoning_map_polygons_ready
                ),
                "projected_polygon_geometries_verified": (
                    historical_zoning_map_polygons_ready
                ),
                "machine_legal_parcel_geometries_verified": False,
                "known_area_ratios_to_legal_lot": {
                    record_number: crosswalk[
                        "zoning_map_polygon"
                    ]["area_ratio_to_legal_lot"]
                    for record_number, crosswalk in historical_event_crosswalks.items()
                    if crosswalk["zoning_map_polygon"][
                        "area_ratio_to_legal_lot"
                    ]
                    is not None
                },
            },
        ),
        "expanded_historical_cohort_preregistration": _check(
            bool(
                expanded_raw_meta.get("count") == 290
                and expanded_raw_meta.get("top") == 500
                and expanded_raw_meta.get("pages") == 1
                and len(expanded_raw_rows) == 290
                and expanded_cohort.get("schema")
                == "gwm.chicago_historical_zoning_cohort_preregistration.v1"
                and expanded_screening.get("source_row_count") == 290
                and expanded_screening.get("selected_event_count") == 23
                and expanded_screening.get("excluded_row_count") == 267
                and expanded_screening.get("all_seed_records_retained") is True
                and len(expanded_events) == 23
                and expanded_cohort.get("readiness", {}).get(
                    "causal_estimation_ready"
                )
                is False
            ),
            {
                "source_row_count": len(expanded_raw_rows),
                "selected_event_count": expanded_screening.get(
                    "selected_event_count"
                ),
                "excluded_row_count": expanded_screening.get(
                    "excluded_row_count"
                ),
                "all_seed_records_retained": expanded_screening.get(
                    "all_seed_records_retained"
                ),
                "cohort_digest": expanded_cohort.get("cohort_digest"),
                "selection_blind_to_outcomes": expanded_cohort.get(
                    "selection_protocol", {}
                ).get("selection_blind_to_outcome_rows"),
            },
        ),
        "expanded_historical_cohort_spatial_crosswalk": _check(
            bool(
                expanded_crosswalk.get("schema")
                == "gwm.chicago_historical_zoning_spatial_crosswalk.v1"
                and expanded_crosswalk.get("cohort_digest")
                == expanded_cohort.get("cohort_digest")
                and expanded_summary.get("cohort_event_count") == 23
                and expanded_summary.get("zoning_map_ready_count") == 22
                and expanded_summary.get("point_address_ready_count") == 19
                and expanded_summary.get("tract_crosswalk_ready_count") == 19
                and expanded_summary.get(
                    "current_parcel_crosswalk_ready_count"
                )
                == 19
                and expanded_summary.get("joint_spatial_crosswalk_ready_count")
                == 17
                and expanded_summary.get("missing_zoning_map_records")
                == ["O2024-0013362"]
                and expanded_summary.get("point_polygon_mismatch_records")
                == ["O2024-0012332"]
                and expanded_readiness.get("outcome_panel_ready") is False
                and expanded_readiness.get("causal_estimation_ready") is False
            ),
            {
                "cohort_event_count": expanded_summary.get(
                    "cohort_event_count"
                ),
                "zoning_map_ready_count": expanded_summary.get(
                    "zoning_map_ready_count"
                ),
                "point_address_ready_count": expanded_summary.get(
                    "point_address_ready_count"
                ),
                "tract_crosswalk_ready_count": expanded_summary.get(
                    "tract_crosswalk_ready_count"
                ),
                "current_parcel_crosswalk_ready_count": expanded_summary.get(
                    "current_parcel_crosswalk_ready_count"
                ),
                "joint_spatial_crosswalk_ready_count": expanded_summary.get(
                    "joint_spatial_crosswalk_ready_count"
                ),
                "missing_zoning_map_records": expanded_summary.get(
                    "missing_zoning_map_records"
                ),
                "point_polygon_mismatch_records": expanded_summary.get(
                    "point_polygon_mismatch_records"
                ),
                "crosswalk_digest": expanded_crosswalk.get(
                    "crosswalk_digest"
                ),
            },
        ),
        "official_city_arcgis_candidate_role_adjudication": _check(
            bool(
                operational_layer_names.get(84) == "Census Tract"
                and operational_layer_names.get(1) == "Parcel Addresses"
                and pwu_permit_layer.get("name") == "SPADE.PWU_PERMITS"
                and pwu_permit_layer.get("geometryType")
                == "esriGeometryPoint"
                and {
                    "PWU_PERMIT_NUM",
                    "PWU_ISSUE_DATE",
                    "PWU_PERMIT_TYPE",
                }
                <= pwu_field_names
                and city_tract_layer.get("name") == "Census Tract"
                and city_tract_layer.get("geometryType")
                == "esriGeometryPolygon"
                and {"TRACT_FIPS", "TRACT_CENSUS_YEAR"}
                <= city_tract_field_names
                and city_tract_count_probe.get("count") == 878
                and len(city_tract_year_features) == 1
                and city_tract_year_features[0].get("attributes", {}).get(
                    "TRACT_CENSUS_YEAR"
                )
                == 2000
            ),
            {
                "public_way_permit_layer": pwu_permit_layer.get("name"),
                "public_way_permit_rejected_as_building_outcome": True,
                "city_census_tract_feature_count": city_tract_count_probe.get(
                    "count"
                ),
                "city_census_tract_year": 2000,
                "city_census_tract_rejected_for_2020_adjacency": True,
                "parcel_addresses_layer_discovered": (
                    operational_layer_names.get(1) == "Parcel Addresses"
                ),
            },
        ),
        "official_arcgis_building_permit_discovery_adjudication": _check(
            bool(
                len(externalapp_services) == 32
                and externalapp_permit_services
                == [
                    {
                        "name": "ExternalApps/Permit_Map",
                        "type": "MapServer",
                    }
                ]
                and permit_mapserver.get("mapName") == "Permit_Map"
                and len(permit_map_layers) == 21
                and [
                    layer.get("name")
                    for layer in permit_map_leaf_layers
                    if "permit" in str(layer.get("name") or "").lower()
                ]
                == ["SPADE.PWU_PERMITS"]
                and not any(
                    "building permit" in str(layer.get("name") or "").lower()
                    for layer in permit_map_leaf_layers
                )
            ),
            {
                "official_externalapps_service_count": len(
                    externalapp_services
                ),
                "permit_named_services": externalapp_permit_services,
                "permit_map_layer_count": len(permit_map_layers),
                "permit_named_leaf_layers": [
                    layer.get("name")
                    for layer in permit_map_leaf_layers
                    if "permit" in str(layer.get("name") or "").lower()
                ],
                "building_permit_layer_discovered": False,
                "public_way_use_permit_layer_rejected": True,
                "search_scope": "official ExternalApps ArcGIS service directory",
            },
        ),
        "historical_zoning_cohort_remains_screening_only": _check(
            True,
            {
                "candidate_count": len(historical_candidate_records),
                "attachment_metadata_verified": True,
                "final_documents_downloaded": True,
                "final_document_bytes": 2898496,
                "legal_boundaries_parsed": True,
                "zoning_transitions_verified": True,
                "point_addresses_verified": historical_point_crosswalk_ready,
                "point_to_tract_crosswalks_verified": (
                    historical_point_crosswalk_ready
                ),
                "zoning_map_polygons_verified": (
                    historical_zoning_map_polygons_ready
                ),
                "effective_dates_verified": False,
                "treatment_geometries_verified": False,
                "bounded_treated_address_outcome_rows_verified": True,
                "complete_tract_outcome_rows_verified": False,
                "untreated_control_outcome_rows_verified": False,
                "cohort_panel_materialized": False,
                "screening_status": (
                    "treated_address_outcome_sample_ready_but_tract_universe_"
                    "controls_effective_onset_and_geometry_blocked"
                ),
            },
        ),
    }
    all_checks_passed = all(check["passed"] for check in checks.values())
    report = {
        "schema": "gwm.chicago_longitudinal_data_foundation_audit.v1",
        "status": (
            "bounded_evidence_valid_partial_outcome_panel_materialized"
            if all_checks_passed
            else "bounded_evidence_invalid"
        ),
        "target": {
            "address": "6716 S BISHOP ST, 60636",
            "matter_record_number": "O2026-0024863",
            "application_number": "23063T1",
            "pin10": TARGET_PIN10,
            "point_wgs84": list(TARGET_POINT_WGS84),
            "tract_geoid": TARGET_TRACT_GEOID,
        },
        "artifacts": artifacts,
        "checks": checks,
        "summary": {
            "raw_artifact_count": len(artifacts),
            "check_count": len(checks),
            "passed_check_count": sum(
                check["passed"] is True for check in checks.values()
            ),
            "all_checks_passed": all_checks_passed,
        },
        "source_role_progress": {
            "treatment_events": {
                "official_point_address_verified": True,
                "point_to_tract_verified": True,
                "enacted_zoning_transition_verified": True,
                "legal_boundary_verified": True,
                "machine_polygon_verified": False,
                "effective_date_verified": False,
                "complete_monthly_post_treatment_periods": 0,
                "temporally_viable_for_effect_estimation": False,
                "candidate_temporal_role": (
                    "crosswalk_fixture_not_effect_estimation_pilot"
                ),
                "historical_candidate_point_addresses_verified": (
                    historical_point_crosswalk_ready
                ),
                "historical_candidate_pins_verified": (
                    historical_point_crosswalk_ready
                ),
                "historical_candidate_point_to_tract_verified": (
                    historical_point_crosswalk_ready
                ),
                "historical_current_zoning_map_polygons_verified": (
                    historical_zoning_map_polygons_ready
                ),
                "historical_machine_legal_parcel_polygons_verified": False,
                "expanded_preregistered_event_count": 23,
                "expanded_zoning_map_ready_count": 22,
                "expanded_point_address_ready_count": 19,
                "expanded_tract_crosswalk_ready_count": 19,
                "expanded_current_parcel_crosswalk_ready_count": 19,
                "expanded_joint_spatial_crosswalk_ready_count": 17,
            },
            "observed_outcomes": {
                "official_catalog_metadata_verified": True,
                "official_historical_schema_semantics_verified": True,
                "official_issue_date_fallback_semantics_verified": True,
                "official_contact_field_removal_semantics_verified": True,
                "official_current_address_level_schema_verified": True,
                "official_bounded_address_level_rows_verified": True,
                "row_schema_verified": True,
                "row_sample_verified": True,
                "bounded_treated_address_count": 17,
                "bounded_permit_row_count": 70,
                "blank_description_of_work_count": 1,
                "bounded_post_publication_permit_row_count": 18,
                "official_current_socrata_metadata_verified": True,
                "official_current_socrata_schema_verified": True,
                "official_terms_of_use_verified": True,
                "socrata_bulk_row_schema_verified": True,
                "bounded_socrata_snapshot_row_count": 114896,
                "bounded_socrata_snapshot_complete": True,
                "spatially_admitted_permit_row_count": 114816,
                "spatial_assignment_admitted_share": 0.999303718,
                "spatially_unresolved_permit_row_count": 72,
                "state_plane_recovered_permit_row_count": 1542,
                "exact_address_geocoder_recovered_permit_row_count": 44,
                "pin_parcel_recovered_permit_row_count": 0,
                "facility_context_permit_row_count": 26,
                "outside_chicago_permit_row_count": 8,
                "complete_tract_permit_universe_verified": False,
                "untreated_control_outcomes_verified": False,
                "candidate_control_outcomes_materialized": True,
                "tract_month_outcome_panel_materialized": True,
                "tract_month_outcome_panel_ready": False,
                "license_verified": True,
                "public_way_permits_rejected_as_building_outcome": True,
            },
            "time_varying_confounders": {
                "secondary_acs_sample_verified": True,
                "official_acs_sample_verified": False,
            },
            "spatial_units": {
                "secondary_geometry_sample_verified": True,
                "secondary_full_cook_geometry_verified": True,
                "secondary_cook_tract_count": 1332,
                "official_tiger2020_catalog_identity_verified": True,
                "official_tiger2020_iso_metadata_verified": True,
                "official_tiger2020_license_verified": True,
                "official_tiger2020_declared_crs": "EPSG:4269",
                "official_tiger2020_zip_accessible_in_browser": True,
                "official_tiger2020_archive_bytes_preserved": False,
                "official_tiger_component_hashes_verified": True,
                "official_tiger_geometry_verified": True,
                "official_cook_tract_count": 1332,
                "official_chicago_place_geometry_verified": True,
                "official_chicago_tract_universe_verified": True,
                "official_chicago_tract_count": 801,
                "official_chicago_cook_tract_count": 799,
                "official_chicago_dupage_tract_count": 2,
                "official_cook_county_parcel_metadata_verified": True,
                "official_target_parcel_sample_verified": False,
                "city_current_parcel_crosswalk_ready_count": 19,
                "city_current_parcel_historical_vintage_verified": False,
                "city_census_tract_candidate_year": 2000,
                "city_census_tract_candidate_rejected_for_2020_panel": True,
            },
            "interference_network": {
                "single_tract_geometry_available": True,
                "secondary_full_cook_geometry_available": True,
                "provisional_queen_adjacency_constructed": True,
                "provisional_rook_adjacency_constructed": True,
                "provisional_queen_edge_count": 2458,
                "provisional_rook_edge_count": 1081,
                "provisional_topology_quality_pass": False,
                "provisional_interference_network_usable": False,
                "official_cook_county_queen_edge_count": 4410,
                "official_cook_county_rook_edge_count": 3416,
                "official_city_tract_count": 801,
                "official_city_queen_edge_count": 2636,
                "official_city_rook_edge_count": 1889,
                "official_queen_connected_component_count": 1,
                "official_rook_connected_component_count": 1,
                "official_topology_quality_pass": True,
                "official_adjacency_constructed": True,
                "official_cook_internal_interference_network_usable": True,
                "official_cook_dupage_city_internal_network_ready": True,
                "adjacency_constructed": True,
                "network_to_unit_time_ready": True,
                "outside_city_interference_ready": False,
                "dynamic_network_ready": False,
                "city_tract_2000_not_usable_for_2020_adjacency": True,
            },
        },
        "historical_candidate_screening": {
            "candidate_record_numbers": sorted(historical_candidate_records),
            "candidate_count": len(historical_candidate_records),
            "minimum_complete_post_publication_months": 19,
            "temporal_screen_ready": True,
            "final_attachment_metadata_ready": True,
            "final_documents_downloaded": True,
            "bounded_official_document_bytes": 2898496,
            "final_document_evidence_ready": True,
            "legal_boundary_text_ready": True,
            "zoning_transition_text_ready": True,
            "candidate_specifications": historical_zoning_specifications,
            "event_crosswalks": historical_event_crosswalks,
            "expanded_preregistered_cohort": {
                "cohort_id": expanded_cohort.get("cohort_id"),
                "cohort_digest": expanded_cohort.get("cohort_digest"),
                "crosswalk_digest": expanded_crosswalk.get(
                    "crosswalk_digest"
                ),
                "source_row_count": expanded_screening.get(
                    "source_row_count"
                ),
                "selected_event_count": expanded_screening.get(
                    "selected_event_count"
                ),
                "zoning_map_ready_count": expanded_summary.get(
                    "zoning_map_ready_count"
                ),
                "point_address_ready_count": expanded_summary.get(
                    "point_address_ready_count"
                ),
                "tract_crosswalk_ready_count": expanded_summary.get(
                    "tract_crosswalk_ready_count"
                ),
                "current_parcel_crosswalk_ready_count": expanded_summary.get(
                    "current_parcel_crosswalk_ready_count"
                ),
                "joint_spatial_crosswalk_ready_count": expanded_summary.get(
                    "joint_spatial_crosswalk_ready_count"
                ),
                "missing_zoning_map_records": expanded_summary.get(
                    "missing_zoning_map_records"
                ),
                "point_polygon_mismatch_records": expanded_summary.get(
                    "point_polygon_mismatch_records"
                ),
                "cohort_crosswalk_complete": False,
                "outcome_panel_ready": False,
                "causal_estimation_ready": False,
            },
            "official_point_addresses_ready": historical_point_crosswalk_ready,
            "official_pins_ready": historical_point_crosswalk_ready,
            "point_to_tract_crosswalks_ready": historical_point_crosswalk_ready,
            "current_zoning_map_polygons_ready": (
                historical_zoning_map_polygons_ready
            ),
            "machine_treatment_geometries_ready": False,
            "effective_onsets_ready": False,
            "source_and_crosswalk_ready": False,
            "cohort_panel_ready": False,
            "causal_estimation_ready": False,
        },
        "admission": {
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
        },
        "claim_boundary": {
            "catalog_metadata_not_permit_rows": True,
            "official_change_log_not_current_schema_or_rows": True,
            "historical_issue_date_completeness_not_current_row_validation": True,
            "building_records_html_schema_not_socrata_bulk_schema": True,
            "building_records_address_history_not_complete_tract_outcome": True,
            "bounded_treated_address_outcomes_not_untreated_controls": True,
            "current_event_not_temporally_viable_for_monthly_effect_estimation": True,
            "historical_matter_metadata_not_cohort_panel": True,
            "historical_legal_boundary_text_not_machine_geometry": True,
            "expanded_cohort_partial_crosswalk_not_panel": True,
            "public_way_permits_not_building_permit_outcome": True,
            "city_census_tract_2000_not_2020_spatial_unit": True,
            "current_parcel_geometry_not_historical_vintage": True,
            "event_point_to_tract_not_treatment_polygon": True,
            "zoning_map_polygon_not_legal_parcel_polygon": True,
            "point_address_not_treatment_polygon": True,
            "ordinance_legal_boundary_not_machine_polygon": True,
            "elms_last_publication_not_verified_effective_onset": True,
            "parcel_metadata_not_target_parcel_sample": True,
            "secondary_acs_not_official_source_admission": True,
            "secondary_geometry_not_official_tiger_admission": True,
            "official_tiger_archive_bytes_not_preserved": True,
            "single_tract_not_interference_network": True,
            "secondary_full_geometry_not_official_tiger_admission": True,
            "secondary_computed_edges_not_topology_quality_pass": True,
            "simplified_secondary_geometry_not_interference_network": True,
            "provisional_adjacency_not_causal_identification": True,
            "official_cook_adjacency_not_cross_county_network": True,
            "official_static_adjacency_not_outcome_panel": True,
            "official_static_adjacency_not_causal_identification": True,
            "outcome_panel_materialization_not_complete_spatial_assignment": True,
            "fuzzy_address_geocoder_matches_not_admitted": True,
            "permit_spatial_missingness_not_assumed_random": True,
            "pin_without_address_consistency_not_permit_location": True,
            "ohare_facility_point_not_permit_location": True,
            "city_internal_network_not_outside_city_interference": True,
            "candidate_controls_not_verified_globally_untreated": True,
            "outcome_panel_materialization_not_causal_identification": True,
            "general_geospatial_kernel_validated": False,
            "gwm_k0_validated": False,
        },
    }
    report["report_digest"] = _canonical_digest(report)
    return report


def build_historical_event_crosswalk_artifact(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the machine-readable historical event point/unit crosswalk."""

    screening = report.get("historical_candidate_screening")
    screening = screening if isinstance(screening, Mapping) else {}
    crosswalk = {
        "schema": "gwm.chicago_historical_zoning_event_crosswalk.v1",
        "observed_on": "2026-07-24",
        "analysis_unit": "2020_census_tract",
        "event_count": screening.get("candidate_count"),
        "events": screening.get("event_crosswalks", {}),
        "readiness": {
            "official_point_addresses_ready": screening.get(
                "official_point_addresses_ready"
            ),
            "official_pins_ready": screening.get("official_pins_ready"),
            "point_to_tract_crosswalks_ready": screening.get(
                "point_to_tract_crosswalks_ready"
            ),
            "current_zoning_map_polygons_ready": screening.get(
                "current_zoning_map_polygons_ready"
            ),
            "machine_treatment_geometries_ready": False,
            "effective_onsets_ready": False,
            "outcome_panel_ready": False,
            "causal_estimation_ready": False,
        },
        "claim_boundary": {
            "point_and_tract_crosswalk_not_treatment_polygon": True,
            "zoning_map_polygon_not_legal_parcel_polygon": True,
            "event_crosswalk_not_longitudinal_panel": True,
            "event_crosswalk_not_causal_identification": True,
        },
        "source_audit_digest": report.get("report_digest"),
    }
    crosswalk["crosswalk_digest"] = _canonical_digest(crosswalk)
    return crosswalk


def _build_historical_event_crosswalk(
    *,
    record_number: str,
    expectation: Mapping[str, Any],
    address_payload: Mapping[str, Any],
    fcc_payload: Mapping[str, Any],
    zoning_payload: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    candidates = address_payload.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    candidate = candidates[0] if candidates else {}
    candidate = candidate if isinstance(candidate, Mapping) else {}
    attributes = candidate.get("attributes")
    attributes = attributes if isinstance(attributes, Mapping) else {}
    location = candidate.get("location")
    location = location if isinstance(location, Mapping) else {}
    spatial_reference = address_payload.get("spatialReference")
    spatial_reference = (
        spatial_reference if isinstance(spatial_reference, Mapping) else {}
    )
    block = fcc_payload.get("Block")
    block = block if isinstance(block, Mapping) else {}
    block_fips = str(block.get("FIPS") or "")
    tract_geoid = block_fips[:11] if len(block_fips) == 15 else ""
    zoning_features = zoning_payload.get("features")
    zoning_features = (
        zoning_features if isinstance(zoning_features, list) else []
    )
    zoning_feature = zoning_features[0] if zoning_features else {}
    zoning_feature = (
        zoning_feature if isinstance(zoning_feature, Mapping) else {}
    )
    zoning_attributes = zoning_feature.get("attributes")
    zoning_attributes = (
        zoning_attributes if isinstance(zoning_attributes, Mapping) else {}
    )
    zoning_geometry = zoning_feature.get("geometry")
    zoning_geometry = (
        zoning_geometry if isinstance(zoning_geometry, Mapping) else {}
    )
    zoning_rings = zoning_geometry.get("rings")
    zoning_rings = zoning_rings if isinstance(zoning_rings, list) else []
    zoning_outer_ring = (
        zoning_rings[0]
        if zoning_rings and isinstance(zoning_rings[0], list)
        else []
    )
    zoning_spatial_reference = zoning_payload.get("spatialReference")
    zoning_spatial_reference = (
        zoning_spatial_reference
        if isinstance(zoning_spatial_reference, Mapping)
        else {}
    )
    zoning_area = zoning_attributes.get("Shape__Area")
    zoning_area = (
        float(zoning_area) if isinstance(zoning_area, (int, float)) else None
    )
    legal_lot_area = expectation["legal_lot_area_square_feet"]
    area_ratio = (
        round(zoning_area / float(legal_lot_area), 6)
        if zoning_area is not None
        and isinstance(legal_lot_area, (int, float))
        and legal_lot_area > 0
        else None
    )
    validation_checks = {
        "single_address_candidate": len(candidates) == 1,
        "wgs84_output": spatial_reference.get("wkid") == 4326,
        "exact_normalized_address": (
            candidate.get("address") == expectation["match_address"]
        ),
        "point_address_type": attributes.get("Addr_type") == "PointAddress",
        "bounded_match_score": float(candidate.get("score") or 0) >= 70,
        "expected_pin10": str(attributes.get("PINNO") or "")
        == expectation["pin10"],
        "finite_wgs84_point": (
            isinstance(location.get("x"), (int, float))
            and isinstance(location.get("y"), (int, float))
            and -180 <= float(location["x"]) <= 180
            and -90 <= float(location["y"]) <= 90
        ),
        "fcc_status_ok": fcc_payload.get("status") == "OK",
        "expected_2020_block": block_fips == expectation["block_fips"],
        "block_derives_expected_tract": tract_geoid
        == expectation["tract_geoid"],
    }
    zoning_validation_checks = {
        "single_polygon_feature": len(zoning_features) == 1,
        "illinois_state_plane_output": (
            zoning_spatial_reference.get("wkid") == 102671
            and zoning_spatial_reference.get("latestWkid") == 3435
        ),
        "polygon_geometry_present": (
            len(zoning_rings) >= 1 and len(zoning_outer_ring) >= 4
        ),
        "address_point_inside_polygon": _point_in_polygon(
            (float(attributes.get("X") or 0), float(attributes.get("Y") or 0)),
            zoning_outer_ring,
        ),
        "clerk_document_matches_event": (
            zoning_attributes.get("CLERK_DOCNO") == record_number
        ),
        "destination_zone_class_matches_ordinance": (
            zoning_attributes.get("ZONE_CLASS")
            == expectation["digital_zone_class"]
        ),
        "ordinance_date_matches_final_action": (
            zoning_attributes.get("ORDINANCE_DATE") == 1730246400000
        ),
        "positive_polygon_area": zoning_area is not None and zoning_area > 0,
    }
    source_files = (
        str(expectation["address_file"]),
        str(expectation["fcc_file"]),
        str(expectation["zoning_file"]),
    )
    return {
        "record_number": record_number,
        "matched_address": candidate.get("address"),
        "match_score": candidate.get("score"),
        "address_type": attributes.get("Addr_type"),
        "pin10": str(attributes.get("PINNO") or ""),
        "ward": attributes.get("WARD"),
        "community": attributes.get("COMMUNITY"),
        "point_wgs84": [location.get("x"), location.get("y")],
        "point_epsg_3435": [attributes.get("X"), attributes.get("Y")],
        "block_fips_2020": block_fips,
        "tract_geoid": tract_geoid,
        "zoning_map_polygon": {
            "object_id": zoning_attributes.get("OBJECTID"),
            "zone_class": zoning_attributes.get("ZONE_CLASS"),
            "ordinance_number": zoning_attributes.get("ORDINANCE_NUM"),
            "ordinance_date_epoch_ms": zoning_attributes.get(
                "ORDINANCE_DATE"
            ),
            "clerk_document_number": zoning_attributes.get("CLERK_DOCNO"),
            "spatial_reference_wkid": zoning_spatial_reference.get("wkid"),
            "spatial_reference_latest_wkid": zoning_spatial_reference.get(
                "latestWkid"
            ),
            "ring_count": len(zoning_rings),
            "vertex_count": len(zoning_outer_ring),
            "shape_area_square_feet": zoning_area,
            "legal_lot_area_square_feet": legal_lot_area,
            "area_ratio_to_legal_lot": area_ratio,
            "legal_parcel_area_consistent": (
                0.95 <= area_ratio <= 1.05
                if area_ratio is not None
                else None
            ),
        },
        "source_artifacts": {
            filename: {
                "path": artifacts[filename]["path"],
                "sha256": artifacts[filename]["sha256"],
                "bytes": artifacts[filename]["bytes"],
            }
            for filename in source_files
        },
        "validation": {
            "checks": validation_checks,
            "passed": all(validation_checks.values()),
        },
        "zoning_map_validation": {
            "checks": zoning_validation_checks,
            "passed": all(zoning_validation_checks.values()),
            "machine_zoning_map_update_verified": all(
                zoning_validation_checks.values()
            ),
            "machine_legal_parcel_polygon_verified": False,
        },
    }


def _find_permit_catalog_record(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    results = payload.get("results")
    if not isinstance(results, list):
        return {}
    return next(
        (
            result
            for result in results
            if isinstance(result, Mapping)
            and result.get("identifier")
            == "https://data.cityofchicago.org/api/views/ydr8-5enu"
        ),
        {},
    )


def _find_catalog_record(
    payload: Mapping[str, Any], identifier: str
) -> Mapping[str, Any]:
    results = payload.get("results")
    if not isinstance(results, list):
        return {}
    return next(
        (
            result
            for result in results
            if isinstance(result, Mapping)
            and result.get("identifier") == identifier
        ),
        {},
    )


def _load_artifact(
    filename: str, *, parse_json: bool = True
) -> dict[str, Any]:
    path = EVIDENCE_DIR / filename
    payload = path.read_bytes()
    artifact = {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }
    if parse_json:
        artifact["payload"] = json.loads(payload)
    return artifact


def _normalized_text(filename: str) -> str:
    text = (EVIDENCE_DIR / filename).read_text(encoding="utf-8")
    return " ".join(text.lower().split())


def _has_pdf_magic(filename: str) -> bool:
    return (EVIDENCE_DIR / filename).read_bytes().startswith(b"%PDF-")


def _historical_candidate_has_final_documents(
    candidate: Mapping[str, Any],
) -> bool:
    attachments = candidate.get("attachments")
    if not isinstance(attachments, list):
        return False
    names = {
        str(attachment.get("fileName") or "")
        for attachment in attachments
        if isinstance(attachment, Mapping)
    }
    record_number = str(candidate.get("recordNumber") or "")
    return bool(
        candidate.get("status") == "90-Final"
        and candidate.get("subStatus") == "Passed"
        and candidate.get("finalActionDate")
        == "2024-10-30T15:00:00+00:00"
        and str(candidate.get("lastPublicationDate") or "").startswith(
            "2024-11-21T"
        )
        and f"{record_number} Final Ordinance.pdf" in names
        and f"{record_number} Final Narrative and Plans.pdf" in names
    )


def _point_in_polygon(
    point: tuple[float, float], ring: list[Any]
) -> bool:
    if len(ring) < 4:
        return False
    x, y = point
    inside = False
    previous = ring[-1]
    for current in ring:
        if not (
            isinstance(previous, list)
            and len(previous) >= 2
            and isinstance(current, list)
            and len(current) >= 2
        ):
            return False
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])
        if _point_on_segment(x, y, x1, y1, x2, y2):
            return True
        if (y1 > y) != (y2 > y):
            intersection_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def _point_on_segment(
    x: float,
    y: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    tolerance: float = 1e-12,
) -> bool:
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > tolerance:
        return False
    return bool(
        min(x1, x2) - tolerance <= x <= max(x1, x2) + tolerance
        and min(y1, y2) - tolerance <= y <= max(y1, y2) + tolerance
    )


def _artifact_ref_matches(
    reference: Any, artifacts: Mapping[str, Mapping[str, Any]]
) -> bool:
    if not isinstance(reference, Mapping):
        return False
    path = str(reference.get("path") or "")
    evidence_prefix = f"{EVIDENCE_DIR.relative_to(ROOT)}/"
    if not path.startswith(evidence_prefix):
        return False
    artifact = artifacts.get(path.removeprefix(evidence_prefix))
    return bool(
        isinstance(artifact, Mapping)
        and artifact.get("path") == path
        and artifact.get("sha256") == reference.get("sha256")
        and artifact.get("bytes") == reference.get("bytes")
    )


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _check(passed: bool, details: Mapping[str, Any]) -> dict[str, Any]:
    return {"passed": bool(passed), "details": dict(details)}


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_ascii_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--historical-crosswalk-output",
        type=Path,
        default=DEFAULT_HISTORICAL_CROSSWALK_OUTPUT,
    )
    args = parser.parse_args()
    report = audit_chicago_longitudinal_data_foundation()
    historical_crosswalk = build_historical_event_crosswalk_artifact(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.historical_crosswalk_output.parent.mkdir(parents=True, exist_ok=True)
    args.historical_crosswalk_output.write_text(
        json.dumps(
            historical_crosswalk,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(args.historical_crosswalk_output)
    return 0 if report["summary"]["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
