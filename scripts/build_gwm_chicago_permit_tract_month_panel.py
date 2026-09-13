#!/usr/bin/env python3
"""Build a fail-closed Chicago permit tract-month panel from official evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

import fiona
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import Point, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence"
)
RAW_DIR = EVIDENCE_DIR / "chicago_socrata_building_permits_2023_2026_raw"
DEFAULT_METADATA = EVIDENCE_DIR / "chicago_socrata_building_permits_metadata_browser.json"
DEFAULT_TERMS = EVIDENCE_DIR / "chicago_data_portal_terms_of_use.html"
DEFAULT_TRACT_SHAPEFILE = (
    EVIDENCE_DIR / "tiger2020_illinois_tract/tl_2020_17_tract.shp"
)
DEFAULT_PLACE_SHAPEFILE = (
    EVIDENCE_DIR / "tiger2020_illinois_place/tl_2020_17_place.shp"
)
DEFAULT_ADJACENCY = (
    EVIDENCE_DIR / "chicago_official_tiger2020_city_tract_adjacency.json"
)
DEFAULT_CROSSWALK = EVIDENCE_DIR / "historical_cohort_spatial_crosswalk.json"
DEFAULT_TRACT_SUMMARY = (
    EVIDENCE_DIR
    / "chicago_socrata_building_permits_2023_2026_tract_summary_browser.json"
)
DEFAULT_RACE_CROSSCHECK = (
    EVIDENCE_DIR / "chicago_socrata_building_permits_race_crosscheck_browser.json"
)
DEFAULT_CURRENT_SAMPLE = (
    EVIDENCE_DIR / "chicago_socrata_building_permits_current_sample_browser.json"
)
DEFAULT_MISSING_COORDINATE_SUPPLEMENT = (
    EVIDENCE_DIR
    / "chicago_socrata_building_permits_2023_2026_missing_coordinates_address_browser.json"
)
DEFAULT_UNRESOLVED_GEOCODER_REQUEST = (
    EVIDENCE_DIR
    / "chicago_building_permits_unresolved_address_geocoder_request.json"
)
DEFAULT_SPATIAL_MISSINGNESS_DIAGNOSTIC = (
    EVIDENCE_DIR
    / "chicago_building_permits_spatial_missingness_diagnostic.json"
)
DEFAULT_UNRESOLVED_GEOCODER_RESPONSE = (
    EVIDENCE_DIR
    / "chicago_building_permits_unresolved_address_geocoder_response.json"
)
DEFAULT_OUTPUT = EVIDENCE_DIR / "chicago_building_permits_2023_2026_tract_month_panel.json"

WINDOW_START = date(2023, 1, 1)
WINDOW_END_EXCLUSIVE = date(2026, 7, 1)
EXPECTED_PART_COUNTS = (25_000, 25_000, 25_000, 25_000, 14_896)
EXPECTED_ROW_COUNT = sum(EXPECTED_PART_COUNTS)
EXPECTED_CITY_TRACT_COUNT = 801
CHICAGO_PLACE_GEOID = "1714000"
COOK_GEOID_PREFIX = "17031"
REQUIRED_ROW_FIELDS = {"id", "permit_", "permit_type", "issue_date"}
SELECTED_FIELDS = (
    "id",
    "permit_",
    "permit_type",
    "application_start_date",
    "issue_date",
    "work_type",
    "reported_cost",
    "census_tract",
    "latitude",
    "longitude",
)
MISSING_COORDINATE_SUPPLEMENT_FIELDS = (
    "id",
    "permit_",
    "permit_type",
    "issue_date",
    "work_type",
    "street_number",
    "street_direction",
    "street_name",
    "pin_list",
    "community_area",
    "ward",
    "xcoordinate",
    "ycoordinate",
    "census_tract",
    "latitude",
    "longitude",
)
EXPECTED_MISSING_COORDINATE_ROW_COUNT = 1_856
REQUIRED_METADATA_FIELDS = {
    "id": "text",
    "permit_": "text",
    "permit_type": "text",
    "application_start_date": "calendar_date",
    "issue_date": "calendar_date",
    "work_type": "text",
    "reported_cost": "number",
    "census_tract": "number",
    "latitude": "number",
    "longitude": "number",
}
REQUIRED_DERIVATIVE_DISCLAIMER = (
    "This site provides applications using data that has been modified for use "
    "from its original source, www.cityofchicago.org, the official website of "
    "the City of Chicago."
)


def build_permit_tract_month_panel(
    *,
    raw_dir: Path = RAW_DIR,
    metadata_path: Path = DEFAULT_METADATA,
    terms_path: Path = DEFAULT_TERMS,
    tract_shapefile_path: Path = DEFAULT_TRACT_SHAPEFILE,
    place_shapefile_path: Path = DEFAULT_PLACE_SHAPEFILE,
    adjacency_path: Path = DEFAULT_ADJACENCY,
    crosswalk_path: Path = DEFAULT_CROSSWALK,
    tract_summary_path: Path = DEFAULT_TRACT_SUMMARY,
    race_crosscheck_path: Path = DEFAULT_RACE_CROSSCHECK,
    current_sample_path: Path = DEFAULT_CURRENT_SAMPLE,
    missing_coordinate_supplement_path: Path = (
        DEFAULT_MISSING_COORDINATE_SUPPLEMENT
    ),
    unresolved_geocoder_request_path: Path = DEFAULT_UNRESOLVED_GEOCODER_REQUEST,
    spatial_missingness_diagnostic_path: Path = (
        DEFAULT_SPATIAL_MISSINGNESS_DIAGNOSTIC
    ),
    unresolved_geocoder_response_path: Path = (
        DEFAULT_UNRESOLVED_GEOCODER_RESPONSE
    ),
) -> dict[str, Any]:
    """Validate, spatially normalize, and aggregate the bounded permit snapshot."""

    metadata = _read_json(metadata_path)
    metadata_validation = _validate_metadata(metadata)
    terms_text = terms_path.read_text(encoding="utf-8")
    terms_validation = _validate_terms(terms_text)
    _validate_capture(metadata_path)
    _validate_capture(terms_path)
    _validate_capture(tract_summary_path)
    _validate_capture(race_crosscheck_path)
    _validate_capture(current_sample_path)
    _validate_capture(missing_coordinate_supplement_path)

    tract_geoids, tract_geometries, tract_validation = _load_illinois_tracts(
        tract_shapefile_path
    )
    chicago_geometry, place_validation = _load_chicago_place(
        place_shapefile_path
    )
    city_tracts, area_shares = _city_tract_universe(
        tract_geoids=tract_geoids,
        tract_geometries=tract_geometries,
        chicago_geometry=chicago_geometry,
    )
    if len(city_tracts) != EXPECTED_CITY_TRACT_COUNT:
        raise ValueError(f"unexpected_city_tract_count:{len(city_tracts)}")

    rows, raw_artifacts, part_summaries = _load_raw_parts(raw_dir)
    missing_coordinate_rows, missing_coordinate_validation = (
        _load_missing_coordinate_supplement(
            missing_coordinate_supplement_path,
            raw_rows=rows,
        )
    )
    state_plane_validation = _validate_state_plane_crosscheck(
        current_sample_path
    )
    tract_summary = _read_json_list(tract_summary_path)
    summary_row_count = sum(int(row["permit_count"]) for row in tract_summary)
    if summary_row_count != EXPECTED_ROW_COUNT:
        raise ValueError(f"tract_summary_row_count_mismatch:{summary_row_count}")
    race_validation = _validate_race_crosscheck(race_crosscheck_path)

    preliminary_assignment = _assign_rows_to_tracts(
        rows=rows,
        tract_geoids=tract_geoids,
        tract_geometries=tract_geometries,
        city_tracts=city_tracts,
        missing_coordinate_rows=missing_coordinate_rows,
    )
    geocoder_points, geocoder_validation = _load_unresolved_geocoder_response(
        request_path=unresolved_geocoder_request_path,
        diagnostic_path=spatial_missingness_diagnostic_path,
        response_path=unresolved_geocoder_response_path,
        preliminary_unresolved_rows=preliminary_assignment["unresolved_rows"],
        tract_geoids=tract_geoids,
        tract_geometries=tract_geometries,
    )
    assignment = _assign_rows_to_tracts(
        rows=rows,
        tract_geoids=tract_geoids,
        tract_geometries=tract_geometries,
        city_tracts=city_tracts,
        missing_coordinate_rows=missing_coordinate_rows,
        geocoder_point_rows=geocoder_points,
    )
    months = _month_sequence(WINDOW_START, WINDOW_END_EXCLUSIVE)
    panel_counts: Counter[tuple[str, str]] = Counter(
        (row["assigned_geoid"], row["month"])
        for row in assignment["admitted_rows"]
    )

    adjacency = _read_json(adjacency_path)
    crosswalk = _read_json(crosswalk_path)
    unit_roles = _unit_roles(
        city_tracts=city_tracts,
        adjacency=adjacency,
        crosswalk=crosswalk,
    )
    units = [
        {
            "tract_geoid": geoid,
            "chicago_area_share": round(area_shares[geoid], 9),
            **unit_roles[geoid],
        }
        for geoid in sorted(city_tracts)
    ]
    panel = [
        {
            "tract_geoid": geoid,
            "month": month,
            "permit_count": panel_counts[(geoid, month)],
            "cohort_role": unit_roles[geoid]["cohort_role"],
        }
        for geoid in sorted(city_tracts)
        for month in months
    ]

    admitted_count = len(assignment["admitted_rows"])
    unresolved_count = len(assignment["unresolved_rows"])
    outside_count = len(assignment["outside_city_rows"])
    complete_spatial_assignment = unresolved_count == 0 and outside_count == 0
    panel_sum = sum(row["permit_count"] for row in panel)
    if panel_sum != admitted_count:
        raise ValueError("panel_count_does_not_equal_admitted_rows")

    artifacts = {
        metadata_path.name: _artifact(metadata_path),
        f"{metadata_path.name}.capture.json": _artifact(_capture_path(metadata_path)),
        terms_path.name: _artifact(terms_path),
        f"{terms_path.name}.capture.json": _artifact(_capture_path(terms_path)),
        tract_summary_path.name: _artifact(tract_summary_path),
        f"{tract_summary_path.name}.capture.json": _artifact(
            _capture_path(tract_summary_path)
        ),
        race_crosscheck_path.name: _artifact(race_crosscheck_path),
        f"{race_crosscheck_path.name}.capture.json": _artifact(
            _capture_path(race_crosscheck_path)
        ),
        current_sample_path.name: _artifact(current_sample_path),
        f"{current_sample_path.name}.capture.json": _artifact(
            _capture_path(current_sample_path)
        ),
        missing_coordinate_supplement_path.name: _artifact(
            missing_coordinate_supplement_path
        ),
        f"{missing_coordinate_supplement_path.name}.capture.json": _artifact(
            _capture_path(missing_coordinate_supplement_path)
        ),
        unresolved_geocoder_request_path.name: _artifact(
            unresolved_geocoder_request_path
        ),
        spatial_missingness_diagnostic_path.name: _artifact(
            spatial_missingness_diagnostic_path
        ),
        unresolved_geocoder_response_path.name: _artifact(
            unresolved_geocoder_response_path
        ),
        adjacency_path.name: _artifact(adjacency_path),
        crosswalk_path.name: _artifact(crosswalk_path),
        **raw_artifacts,
        **{
            str(path.relative_to(EVIDENCE_DIR)): _artifact(path)
            for path in _shapefile_components(tract_shapefile_path)
        },
        **{
            str(path.relative_to(EVIDENCE_DIR)): _artifact(path)
            for path in _shapefile_components(place_shapefile_path)
        },
    }
    role_counts = Counter(unit["cohort_role"] for unit in units)
    result = {
        "schema": "gwm.chicago_building_permits_tract_month_panel.v1",
        "observed_on": "2026-07-24",
        "source": {
            "publisher": "City of Chicago Department of Buildings",
            "dataset_id": "ydr8-5enu",
            "canonical_url": "https://data.cityofchicago.org/d/ydr8-5enu",
            "access_boundary": "browser_or_waf",
            "license": "City of Chicago Data Terms of Use",
            "license_url": (
                "https://www.chicago.gov/city/en/narr/foia/"
                "data_disclaimer.html"
            ),
            "required_derivative_disclaimer": REQUIRED_DERIVATIVE_DISCLAIMER,
            "permit_time_semantics": (
                "ISSUE_DATE is an administrative readiness-or-issuance date and "
                "does not prove work start, completion, or realized construction"
            ),
        },
        "query_contract": {
            "window_start_inclusive": WINDOW_START.isoformat(),
            "window_end_exclusive": WINDOW_END_EXCLUSIVE.isoformat(),
            "complete_month_count": len(months),
            "selected_fields": list(SELECTED_FIELDS),
            "excluded_sensitive_field_prefixes": ["contact_"],
            "order_by": "id",
            "part_counts": list(EXPECTED_PART_COUNTS),
            "row_count": len(rows),
            "metadata_validation": metadata_validation,
            "terms_validation": terms_validation,
            "part_summaries": part_summaries,
            "missing_coordinate_supplement_validation": (
                missing_coordinate_validation
            ),
            "unresolved_geocoder_validation": geocoder_validation,
        },
        "spatial_contract": {
            "target_unit": "2020_census_tract",
            "tract_source": "official TIGER/Line 2020 Illinois tracts",
            "city_source": "official TIGER/Line 2020 Illinois places",
            "city_place_geoid": CHICAGO_PLACE_GEOID,
            "city_tract_membership_rule": "positive area intersection with Chicago city",
            "city_tract_count": len(city_tracts),
            "tract_validation": tract_validation,
            "place_validation": place_validation,
            "assignment_priority": (
                "unambiguous published WGS84 point; unambiguous transformed "
                "EPSG:3435 State Plane point when WGS84 is unavailable; valid "
                "score-100 official AddressPoints result when both published "
                "coordinate sources are unavailable; valid source tract code "
                "only when all point sources are unavailable"
            ),
            "state_plane_crosscheck": state_plane_validation,
        },
        "assignment_diagnostics": {
            **assignment["summary"],
            "admitted_row_count": admitted_count,
            "unresolved_row_count": unresolved_count,
            "outside_city_row_count": outside_count,
            "admitted_share": round(admitted_count / len(rows), 9),
            "unresolved_examples": assignment["unresolved_rows"][:25],
            "outside_city_examples": assignment["outside_city_rows"][:25],
            "direct_point_conflict_examples": assignment[
                "direct_point_conflict_examples"
            ][:25],
        },
        "panel_summary": {
            "unit_count": len(units),
            "month_count": len(months),
            "panel_row_count": len(panel),
            "permit_count": panel_sum,
            "zero_cell_count": sum(row["permit_count"] == 0 for row in panel),
            "cohort_role_counts": dict(sorted(role_counts.items())),
            "target_event_tract_count": role_counts["treated_event_tract"],
            "candidate_control_tract_count": role_counts[
                "candidate_control_outside_queen_buffer"
            ],
            "race_crosscheck": race_validation,
        },
        "units": units,
        "panel": panel,
        "artifacts": artifacts,
        "readiness": {
            "official_current_socrata_schema_verified": True,
            "official_row_snapshot_complete": True,
            "official_terms_of_use_verified": True,
            "official_2020_chicago_tract_universe_verified": True,
            "tract_month_panel_materialized": True,
            "complete_spatial_assignment_ready": complete_spatial_assignment,
            "candidate_control_outcomes_materialized": True,
            "verified_untreated_control_status_ready": False,
            "treatment_effective_onsets_ready": False,
            "causal_estimation_ready": False,
        },
        "claim_boundary": {
            "permit_issue_not_construction_start": True,
            "permit_issue_not_work_completion": True,
            "current_status_fields_excluded_to_reduce_future_state_leakage": True,
            "candidate_controls_not_verified_globally_untreated": True,
            "pre_registered_cohort_not_complete_zoning_event_universe": True,
            "spatially_unresolved_rows_not_silently_imputed": True,
            "panel_materialization_not_causal_identification": True,
            "paper6_effect_estimation_validated": False,
            "general_geospatial_kernel_validated": False,
            "gwm_k0_validated": False,
        },
    }
    result["panel_digest"] = _canonical_digest(result)
    return result


def _validate_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    if metadata.get("id") != "ydr8-5enu":
        raise ValueError("metadata_dataset_id_mismatch")
    if metadata.get("attribution") != "City of Chicago":
        raise ValueError("metadata_attribution_mismatch")
    if metadata.get("provenance") != "official":
        raise ValueError("metadata_provenance_not_official")
    if metadata.get("publicationStage") != "published":
        raise ValueError("metadata_not_published")
    if metadata.get("licenseId") != "SEE_TERMS_OF_USE":
        raise ValueError("metadata_license_id_mismatch")
    columns = metadata.get("columns")
    columns = columns if isinstance(columns, list) else []
    types = {
        str(column.get("fieldName")): str(column.get("dataTypeName"))
        for column in columns
        if isinstance(column, Mapping)
    }
    mismatches = {
        field: {"expected": expected, "observed": types.get(field)}
        for field, expected in REQUIRED_METADATA_FIELDS.items()
        if types.get(field) != expected
    }
    if mismatches:
        raise ValueError(f"metadata_field_type_mismatch:{mismatches}")
    return {
        "dataset_id": metadata.get("id"),
        "row_count_at_capture": int(
            next(
                column["cachedContents"]["count"]
                for column in columns
                if isinstance(column, Mapping) and column.get("fieldName") == "id"
            )
        ),
        "rows_updated_at_epoch": metadata.get("rowsUpdatedAt"),
        "column_count": len(columns),
        "required_field_types_verified": True,
        "license_id": metadata.get("licenseId"),
        "daily_update_frequency_verified": (
            metadata.get("metadata", {})
            .get("custom_fields", {})
            .get("Metadata", {})
            .get("Frequency")
            == "Data are updated daily"
        ),
    }


def _validate_terms(terms_text: str) -> dict[str, Any]:
    required = (
        "DISCLAIMER OF LIABILITY",
        "USE OF DATA",
        "RESERVATION OF RIGHTS",
        REQUIRED_DERIVATIVE_DISCLAIMER,
    )
    missing = [value for value in required if value not in terms_text]
    if missing:
        raise ValueError(f"terms_required_text_missing:{missing}")
    return {
        "city_terms_page_verified": True,
        "derivative_disclaimer_required": True,
        "as_is_without_warranty": "as is" in terms_text.lower(),
        "city_may_require_termination_of_use": (
            "terminate any and all display" in terms_text
        ),
    }


def _load_cook_tracts(
    shapefile_path: Path,
) -> tuple[list[str], list[Any], dict[str, Any]]:
    geoids: list[str] = []
    geometries = []
    with fiona.open(shapefile_path) as source:
        if source.crs.to_epsg() != 4269 or len(source) != 3265:
            raise ValueError("official_tract_source_identity_mismatch")
        for feature in source:
            properties = feature["properties"]
            if properties["STATEFP"] == "17" and properties["COUNTYFP"] == "031":
                geoids.append(str(properties["GEOID"]))
                geometries.append(shape(feature["geometry"]))
    if len(geoids) != 1332 or len(set(geoids)) != 1332:
        raise ValueError("official_cook_tract_count_mismatch")
    if not all(geometry.is_valid and not geometry.is_empty for geometry in geometries):
        raise ValueError("official_cook_tract_geometry_invalid")
    return geoids, geometries, {
        "state_feature_count": 3265,
        "cook_tract_count": len(geoids),
        "crs": "EPSG:4269",
        "all_geometries_valid_nonempty": True,
    }


def _load_illinois_tracts(
    shapefile_path: Path,
) -> tuple[list[str], list[Any], dict[str, Any]]:
    geoids: list[str] = []
    geometries = []
    county_counts: Counter[str] = Counter()
    with fiona.open(shapefile_path) as source:
        if source.crs.to_epsg() != 4269 or len(source) != 3265:
            raise ValueError("official_tract_source_identity_mismatch")
        for feature in source:
            properties = feature["properties"]
            if properties["STATEFP"] != "17":
                raise ValueError("non_illinois_tract_in_state_source")
            geoid = str(properties["GEOID"])
            expected = (
                f"17{properties['COUNTYFP']}{properties['TRACTCE']}"
            )
            if geoid != expected:
                raise ValueError(f"official_tract_geoid_mismatch:{geoid}")
            geoids.append(geoid)
            geometries.append(shape(feature["geometry"]))
            county_counts[str(properties["COUNTYFP"])] += 1
    if len(geoids) != 3265 or len(set(geoids)) != 3265:
        raise ValueError("official_illinois_tract_count_mismatch")
    if county_counts["031"] != 1332 or county_counts["043"] != 219:
        raise ValueError("official_cook_or_dupage_tract_count_mismatch")
    if not all(geometry.is_valid and not geometry.is_empty for geometry in geometries):
        raise ValueError("official_illinois_tract_geometry_invalid")
    return geoids, geometries, {
        "state_feature_count": len(geoids),
        "cook_tract_count": county_counts["031"],
        "dupage_tract_count": county_counts["043"],
        "crs": "EPSG:4269",
        "all_geometries_valid_nonempty": True,
    }


def _load_chicago_place(shapefile_path: Path) -> tuple[Any, dict[str, Any]]:
    matches = []
    with fiona.open(shapefile_path) as source:
        if source.crs.to_epsg() != 4269 or len(source) != 1466:
            raise ValueError("official_place_source_identity_mismatch")
        for feature in source:
            if feature["properties"]["GEOID"] == CHICAGO_PLACE_GEOID:
                matches.append(feature)
    if len(matches) != 1:
        raise ValueError(f"chicago_place_match_count:{len(matches)}")
    feature = matches[0]
    properties = feature["properties"]
    if properties["NAME"] != "Chicago" or properties["NAMELSAD"] != "Chicago city":
        raise ValueError("chicago_place_name_mismatch")
    geometry = shape(feature["geometry"])
    if not geometry.is_valid or geometry.is_empty:
        raise ValueError("chicago_place_geometry_invalid")
    return geometry, {
        "state_place_count": 1466,
        "chicago_place_geoid": CHICAGO_PLACE_GEOID,
        "name": properties["NAME"],
        "namelsad": properties["NAMELSAD"],
        "aland_square_metres": properties["ALAND"],
        "awater_square_metres": properties["AWATER"],
        "crs": "EPSG:4269",
    }


def _city_tract_universe(
    *,
    tract_geoids: list[str],
    tract_geometries: list[Any],
    chicago_geometry: Any,
) -> tuple[set[str], dict[str, float]]:
    projector = Transformer.from_crs(4269, 3435, always_xy=True).transform
    projected_city = transform(projector, chicago_geometry)
    city_tracts: set[str] = set()
    shares: dict[str, float] = {}
    for geoid, geometry in zip(tract_geoids, tract_geometries, strict=True):
        projected_tract = transform(projector, geometry)
        intersection_area = projected_tract.intersection(projected_city).area
        share = intersection_area / projected_tract.area
        if share > 0:
            city_tracts.add(geoid)
            shares[geoid] = share
    return city_tracts, shares


def _load_raw_parts(
    raw_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {}
    summaries = []
    previous_id: str | None = None
    all_ids: set[str] = set()
    all_permits: set[str] = set()
    for part_index, expected_count in enumerate(EXPECTED_PART_COUNTS):
        path = raw_dir / f"part-{part_index:05d}.json"
        part = _read_json_list(path)
        if len(part) != expected_count:
            raise ValueError(
                f"raw_part_count_mismatch:{part_index}:{len(part)}:{expected_count}"
            )
        capture = _validate_capture(path)
        query = parse_qs(urlparse(capture["source_url"]).query)
        if query.get("$select") != [",".join(SELECTED_FIELDS)]:
            raise ValueError(f"raw_part_select_mismatch:{part_index}")
        if query.get("$order") != ["id"]:
            raise ValueError(f"raw_part_order_mismatch:{part_index}")
        if query.get("$limit") != ["25000"]:
            raise ValueError(f"raw_part_limit_mismatch:{part_index}")
        if query.get("$offset") != [str(part_index * 25_000)]:
            raise ValueError(f"raw_part_offset_mismatch:{part_index}")
        where = query.get("$where", [""])[0]
        if (
            "2023-01-01T00:00:00.000" not in where
            or "2026-07-01T00:00:00.000" not in where
        ):
            raise ValueError(f"raw_part_time_window_mismatch:{part_index}")
        part_ids = []
        part_permits = []
        for row_index, raw_row in enumerate(part):
            if not isinstance(raw_row, Mapping):
                raise ValueError(f"raw_row_not_object:{part_index}:{row_index}")
            row = dict(raw_row)
            missing = REQUIRED_ROW_FIELDS - set(row)
            if missing:
                raise ValueError(
                    f"raw_required_fields_missing:{part_index}:{row_index}:{missing}"
                )
            row_id = str(row["id"])
            permit = str(row["permit_"])
            if row_id in all_ids or permit in all_permits:
                raise ValueError(f"raw_cross_part_duplicate:{row_id}:{permit}")
            if previous_id is not None and row_id <= previous_id:
                raise ValueError(f"raw_global_order_invalid:{previous_id}:{row_id}")
            issue_date = _parse_socrata_date(row["issue_date"])
            if not (WINDOW_START <= issue_date < WINDOW_END_EXCLUSIVE):
                raise ValueError(f"raw_issue_date_outside_window:{row_id}")
            previous_id = row_id
            all_ids.add(row_id)
            all_permits.add(permit)
            part_ids.append(row_id)
            part_permits.append(permit)
            rows.append(row)
        relative = str(path.relative_to(EVIDENCE_DIR))
        artifacts[relative] = _artifact(path)
        artifacts[f"{relative}.capture.json"] = _artifact(_capture_path(path))
        summaries.append(
            {
                "part_index": part_index,
                "row_count": len(part),
                "first_id": part_ids[0],
                "last_id": part_ids[-1],
                "unique_id_count": len(set(part_ids)),
                "unique_permit_count": len(set(part_permits)),
                "sha256": artifacts[relative]["sha256"],
            }
        )
    if len(rows) != EXPECTED_ROW_COUNT:
        raise ValueError(f"raw_total_count_mismatch:{len(rows)}")
    return rows, artifacts, summaries


def _load_missing_coordinate_supplement(
    path: Path,
    *,
    raw_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    supplement = _read_json_list(path)
    if len(supplement) != EXPECTED_MISSING_COORDINATE_ROW_COUNT:
        raise ValueError(
            "missing_coordinate_supplement_count_mismatch:"
            f"{len(supplement)}"
        )
    capture = _validate_capture(path)
    query = parse_qs(urlparse(capture["source_url"]).query)
    if query.get("$select") != [
        ",".join(MISSING_COORDINATE_SUPPLEMENT_FIELDS)
    ]:
        raise ValueError("missing_coordinate_supplement_select_mismatch")
    if query.get("$order") != ["id"] or query.get("$limit") != ["5000"]:
        raise ValueError("missing_coordinate_supplement_order_or_limit_mismatch")
    where = query.get("$where", [""])[0]
    if (
        "2023-01-01T00:00:00.000" not in where
        or "2026-07-01T00:00:00.000" not in where
        or "latitude is null" not in where
    ):
        raise ValueError("missing_coordinate_supplement_where_mismatch")

    raw_missing_latitude = {
        str(row["id"]): row
        for row in raw_rows
        if _finite_float(row.get("latitude")) is None
    }
    by_id: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(supplement):
        if not isinstance(value, Mapping):
            raise ValueError(f"missing_coordinate_row_not_object:{index}")
        row = dict(value)
        row_id = str(row.get("id") or "")
        if not row_id or row_id in by_id:
            raise ValueError(f"missing_coordinate_id_invalid:{index}:{row_id}")
        raw = raw_missing_latitude.get(row_id)
        if raw is None:
            raise ValueError(f"missing_coordinate_id_not_in_raw:{row_id}")
        for field in ("permit_", "permit_type", "issue_date", "work_type"):
            if row.get(field) != raw.get(field):
                raise ValueError(
                    f"missing_coordinate_field_mismatch:{row_id}:{field}"
                )
        by_id[row_id] = row
    if set(by_id) != set(raw_missing_latitude):
        raise ValueError("missing_coordinate_supplement_id_universe_mismatch")
    return by_id, {
        "row_count": len(by_id),
        "raw_missing_latitude_row_count": len(raw_missing_latitude),
        "id_universe_matches_raw_snapshot": True,
        "contact_fields_excluded": not any(
            field.startswith("contact_")
            for field in MISSING_COORDINATE_SUPPLEMENT_FIELDS
        ),
        "state_plane_xy_present_count": sum(
            _finite_float(row.get("xcoordinate")) is not None
            and _finite_float(row.get("ycoordinate")) is not None
            for row in by_id.values()
        ),
        "public_street_number_and_name_present_count": sum(
            row.get("street_number") not in (None, "")
            and row.get("street_name") not in (None, "")
            for row in by_id.values()
        ),
    }


def _validate_state_plane_crosscheck(path: Path) -> dict[str, Any]:
    rows = _read_json_list(path)
    if len(rows) != 1:
        raise ValueError("current_sample_state_plane_crosscheck_count_mismatch")
    row = rows[0]
    if not isinstance(row, Mapping):
        raise ValueError("current_sample_state_plane_crosscheck_row_invalid")
    x = _finite_float(row.get("xcoordinate"))
    y = _finite_float(row.get("ycoordinate"))
    observed_latitude = _finite_float(row.get("latitude"))
    observed_longitude = _finite_float(row.get("longitude"))
    if None in (x, y, observed_latitude, observed_longitude):
        raise ValueError("current_sample_state_plane_crosscheck_fields_missing")
    longitude, latitude = Transformer.from_crs(
        3435, 4269, always_xy=True
    ).transform(x, y)
    longitude_error = abs(longitude - observed_longitude)
    latitude_error = abs(latitude - observed_latitude)
    if longitude_error > 1e-8 or latitude_error > 1e-8:
        raise ValueError("state_plane_to_wgs84_crosscheck_failed")
    return {
        "source_crs": "EPSG:3435",
        "target_crs": "EPSG:4269",
        "sample_id": str(row.get("id")),
        "longitude_absolute_error_degrees": longitude_error,
        "latitude_absolute_error_degrees": latitude_error,
        "tolerance_degrees": 1e-8,
        "passed": True,
    }


def _load_unresolved_geocoder_response(
    *,
    request_path: Path,
    diagnostic_path: Path,
    response_path: Path,
    preliminary_unresolved_rows: list[dict[str, Any]],
    tract_geoids: list[str],
    tract_geometries: list[Any],
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    request = _read_json(request_path)
    diagnostic = _read_json(diagnostic_path)
    response = _read_json(response_path)
    diagnostic_without_digest = dict(diagnostic)
    diagnostic_digest = diagnostic_without_digest.pop("diagnostic_digest", None)
    if diagnostic_digest != _canonical_digest(diagnostic_without_digest):
        raise ValueError("spatial_missingness_diagnostic_digest_mismatch")
    geocoder_contract = diagnostic.get("geocoder_contract")
    geocoder_contract = (
        geocoder_contract if isinstance(geocoder_contract, Mapping) else {}
    )
    if geocoder_contract.get("request_digest") != _canonical_digest(request):
        raise ValueError("unresolved_geocoder_request_digest_mismatch")

    records = request.get("records")
    manifest = diagnostic.get("address_manifest")
    locations = response.get("locations")
    if not (
        isinstance(records, list)
        and isinstance(manifest, list)
        and isinstance(locations, list)
        and len(records) == len(manifest) == len(locations) == 47
    ):
        raise ValueError("unresolved_geocoder_record_count_mismatch")
    if response.get("spatialReference", {}).get("wkid") != 4326:
        raise ValueError("unresolved_geocoder_response_crs_mismatch")

    manifest_by_id: dict[int, Mapping[str, Any]] = {}
    manifest_row_ids: set[str] = set()
    for item in manifest:
        if not isinstance(item, Mapping):
            raise ValueError("unresolved_geocoder_manifest_item_invalid")
        object_id = int(item.get("object_id") or 0)
        if object_id in manifest_by_id:
            raise ValueError("unresolved_geocoder_manifest_object_id_duplicate")
        manifest_by_id[object_id] = item
        manifest_row_ids.update(str(value) for value in item.get("permit_ids", []))
    preliminary_ids = {
        str(row["id"]) for row in preliminary_unresolved_rows
    }
    if manifest_row_ids != preliminary_ids or len(preliminary_ids) != 116:
        raise ValueError("unresolved_geocoder_manifest_row_universe_mismatch")

    request_by_id = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("unresolved_geocoder_request_record_invalid")
        attributes = record.get("attributes")
        attributes = attributes if isinstance(attributes, Mapping) else {}
        object_id = int(attributes.get("OBJECTID") or 0)
        request_by_id[object_id] = str(attributes.get("Address") or "")
    if set(request_by_id) != set(manifest_by_id):
        raise ValueError("unresolved_geocoder_request_object_ids_mismatch")
    if any(
        request_by_id[object_id] != str(item.get("address") or "")
        for object_id, item in manifest_by_id.items()
    ):
        raise ValueError("unresolved_geocoder_request_address_mismatch")

    tree = STRtree(tract_geometries)
    admitted: dict[str, dict[str, float]] = {}
    returned_ids: set[int] = set()
    exact_address_count = 0
    fuzzy_point_address_count = 0
    unmatched_address_count = 0
    for location in locations:
        if not isinstance(location, Mapping):
            raise ValueError("unresolved_geocoder_location_invalid")
        attributes = location.get("attributes")
        attributes = attributes if isinstance(attributes, Mapping) else {}
        object_id = int(attributes.get("ResultID") or 0)
        if object_id in returned_ids or object_id not in manifest_by_id:
            raise ValueError("unresolved_geocoder_result_id_invalid")
        returned_ids.add(object_id)
        score = _finite_float(location.get("score")) or 0.0
        address_type = str(attributes.get("Addr_type") or "")
        if score == 0:
            unmatched_address_count += 1
            continue
        if score != 100 or address_type != "PointAddress":
            fuzzy_point_address_count += 1
            continue
        requested_address = request_by_id[object_id]
        matched_address = str(attributes.get("Match_addr") or "")
        if not matched_address.startswith(requested_address):
            raise ValueError("unresolved_geocoder_exact_address_prefix_mismatch")
        point = location.get("location")
        point = point if isinstance(point, Mapping) else {}
        longitude = _finite_float(point.get("x"))
        latitude = _finite_float(point.get("y"))
        if (
            longitude is None
            or latitude is None
            or not -180 <= longitude <= 180
            or not -90 <= latitude <= 90
        ):
            raise ValueError("unresolved_geocoder_exact_point_invalid")
        geoid = _unique_point_geoid(
            point=Point(longitude, latitude),
            tree=tree,
            tract_geoids=tract_geoids,
        )
        if geoid is None:
            raise ValueError("unresolved_geocoder_exact_point_not_unique_tract")
        exact_address_count += 1
        for row_id in manifest_by_id[object_id].get("permit_ids", []):
            admitted[str(row_id)] = {
                "longitude": longitude,
                "latitude": latitude,
            }
    if returned_ids != set(manifest_by_id):
        raise ValueError("unresolved_geocoder_result_id_universe_mismatch")
    if exact_address_count != 8 or len(admitted) != 44:
        raise ValueError("unresolved_geocoder_exact_admission_count_mismatch")
    return admitted, {
        "request_record_count": len(records),
        "response_location_count": len(locations),
        "result_id_universe_complete": True,
        "exact_score_100_point_address_count": exact_address_count,
        "exact_score_100_recovered_row_count": len(admitted),
        "fuzzy_point_address_count": fuzzy_point_address_count,
        "unmatched_address_count": unmatched_address_count,
        "fuzzy_matches_admitted": False,
        "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
        "response_sha256": hashlib.sha256(response_path.read_bytes()).hexdigest(),
    }


def _assign_rows_to_tracts(
    *,
    rows: list[dict[str, Any]],
    tract_geoids: list[str],
    tract_geometries: list[Any],
    city_tracts: set[str],
    missing_coordinate_rows: Mapping[str, Mapping[str, Any]] | None = None,
    geocoder_point_rows: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, Any]:
    tree = STRtree(tract_geometries)
    state_plane_to_geographic = Transformer.from_crs(
        3435, 4269, always_xy=True
    )
    official_geoids = set(tract_geoids)
    admitted = []
    unresolved = []
    outside_city = []
    methods: Counter[str] = Counter()
    direct_point_conflicts = []
    missing_application_start = 0
    missing_coordinates = 0
    missing_source_tract = 0
    state_plane_candidate_count = 0
    invalid_or_missing_state_plane_count = 0
    coordinate_supplement = missing_coordinate_rows or {}
    geocoder_points = geocoder_point_rows or {}
    address_geocoder_candidate_count = 0
    for row in rows:
        row_id = str(row["id"])
        issue_date = _parse_socrata_date(row["issue_date"])
        if not row.get("application_start_date"):
            missing_application_start += 1
        source_geoid = _source_tract_geoid(row.get("census_tract"), official_geoids)
        if row.get("census_tract") in (None, ""):
            missing_source_tract += 1
        point_geoid = None
        point_source = None
        latitude = _finite_float(row.get("latitude"))
        longitude = _finite_float(row.get("longitude"))
        if latitude is None or longitude is None:
            missing_coordinates += 1
        elif -90 <= latitude <= 90 and -180 <= longitude <= 180:
            point = Point(longitude, latitude)
            point_geoid = _unique_point_geoid(
                point=point,
                tree=tree,
                tract_geoids=tract_geoids,
            )
            point_source = "published_wgs84"
        if point_source is None and row_id in coordinate_supplement:
            supplement = coordinate_supplement[row_id]
            xcoordinate = _finite_float(supplement.get("xcoordinate"))
            ycoordinate = _finite_float(supplement.get("ycoordinate"))
            if (
                xcoordinate is not None
                and ycoordinate is not None
                and 100_000 < xcoordinate < 2_000_000
                and 100_000 < ycoordinate < 3_000_000
            ):
                state_plane_candidate_count += 1
                transformed_longitude, transformed_latitude = (
                    state_plane_to_geographic.transform(
                        xcoordinate,
                        ycoordinate,
                    )
                )
                point_geoid = _unique_point_geoid(
                    point=Point(transformed_longitude, transformed_latitude),
                    tree=tree,
                    tract_geoids=tract_geoids,
                )
                point_source = "state_plane_epsg3435"
            else:
                invalid_or_missing_state_plane_count += 1
        if point_source is None and row_id in geocoder_points:
            geocoder_point = geocoder_points[row_id]
            geocoder_longitude = _finite_float(geocoder_point.get("longitude"))
            geocoder_latitude = _finite_float(geocoder_point.get("latitude"))
            if geocoder_longitude is None or geocoder_latitude is None:
                raise ValueError(f"geocoder_point_invalid:{row_id}")
            address_geocoder_candidate_count += 1
            point_geoid = _unique_point_geoid(
                point=Point(geocoder_longitude, geocoder_latitude),
                tree=tree,
                tract_geoids=tract_geoids,
            )
            point_source = "official_address_geocoder"

        if point_geoid and source_geoid and point_geoid == source_geoid:
            assigned_geoid = point_geoid
            method = _point_assignment_method(point_source, "agree")
        elif point_geoid and source_geoid and point_geoid != source_geoid:
            assigned_geoid = point_geoid
            method = _point_assignment_method(point_source, "conflict")
            direct_point_conflicts.append(
                {
                    "id": row_id,
                    "permit_": row["permit_"],
                    "source_geoid": source_geoid,
                    "point_geoid": point_geoid,
                    "coordinate_source": point_source,
                }
            )
        elif point_geoid:
            assigned_geoid = point_geoid
            method = _point_assignment_method(point_source, "recover")
        elif source_geoid:
            assigned_geoid = source_geoid
            method = "source_code_fallback_without_point"
        else:
            unresolved.append(
                {
                    "id": row_id,
                    "permit_": row["permit_"],
                    "census_tract": row.get("census_tract"),
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude"),
                }
            )
            methods["unresolved"] += 1
            continue

        record = {
            "id": row_id,
            "permit_": str(row["permit_"]),
            "assigned_geoid": assigned_geoid,
            "month": issue_date.strftime("%Y-%m"),
            "assignment_method": method,
        }
        methods[method] += 1
        if assigned_geoid not in city_tracts:
            outside_city.append(record)
            continue
        admitted.append(record)

    return {
        "admitted_rows": admitted,
        "unresolved_rows": unresolved,
        "outside_city_rows": outside_city,
        "direct_point_conflict_examples": direct_point_conflicts,
        "summary": {
            "assignment_method_counts": dict(sorted(methods.items())),
            "direct_point_conflict_count": len(direct_point_conflicts),
            "missing_application_start_date_count": missing_application_start,
            "missing_coordinate_count": missing_coordinates,
            "missing_source_census_tract_count": missing_source_tract,
            "state_plane_candidate_count": state_plane_candidate_count,
            "invalid_or_missing_state_plane_count": (
                invalid_or_missing_state_plane_count
            ),
            "address_geocoder_candidate_count": address_geocoder_candidate_count,
        },
    }


def _unique_point_geoid(
    *,
    point: Point,
    tree: STRtree,
    tract_geoids: list[str],
) -> str | None:
    indices = [int(value) for value in tree.query(point, predicate="within")]
    return tract_geoids[indices[0]] if len(indices) == 1 else None


def _point_assignment_method(point_source: str | None, relation: str) -> str:
    methods = {
        ("published_wgs84", "agree"): "point_and_source_code_agree",
        ("published_wgs84", "conflict"): (
            "point_overrides_conflicting_source_code"
        ),
        ("published_wgs84", "recover"): (
            "point_recovers_missing_or_legacy_source_code"
        ),
        ("state_plane_epsg3435", "agree"): (
            "state_plane_and_source_code_agree"
        ),
        ("state_plane_epsg3435", "conflict"): (
            "state_plane_overrides_conflicting_source_code"
        ),
        ("state_plane_epsg3435", "recover"): (
            "state_plane_recovers_missing_or_legacy_source_code"
        ),
        ("official_address_geocoder", "agree"): (
            "address_geocoder_and_source_code_agree"
        ),
        ("official_address_geocoder", "conflict"): (
            "address_geocoder_overrides_conflicting_source_code"
        ),
        ("official_address_geocoder", "recover"): (
            "address_geocoder_recovers_missing_or_legacy_source_code"
        ),
    }
    try:
        return methods[(point_source, relation)]
    except KeyError as error:
        raise ValueError(
            f"unknown_point_assignment_method:{point_source}:{relation}"
        ) from error


def _unit_roles(
    *,
    city_tracts: set[str],
    adjacency: Mapping[str, Any],
    crosswalk: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    treated_events: dict[str, list[str]] = defaultdict(list)
    for event in crosswalk.get("events", []):
        if not isinstance(event, Mapping):
            continue
        if event.get("spatial_consistency", {}).get("ready") is not True:
            continue
        geoid = str(event.get("tract_crosswalk", {}).get("tract_geoid") or "")
        treated_events[geoid].append(str(event.get("record_number") or ""))
    treated = set(treated_events)
    if len(treated) != 17 or not treated <= city_tracts:
        raise ValueError("treated_event_tract_universe_mismatch")

    queen_neighbors: dict[str, set[str]] = defaultdict(set)
    rook_neighbors: dict[str, set[str]] = defaultdict(set)
    for key, target in (("queen_edges", queen_neighbors), ("rook_edges", rook_neighbors)):
        for edge in adjacency.get(key, []):
            source = str(edge["source_geoid"])
            destination = str(edge["target_geoid"])
            target[source].add(destination)
            target[destination].add(source)
    queen_buffer = set().union(*(queen_neighbors[geoid] for geoid in treated))
    rook_buffer = set().union(*(rook_neighbors[geoid] for geoid in treated))
    roles = {}
    for geoid in city_tracts:
        if geoid in treated:
            role = "treated_event_tract"
        elif geoid in queen_buffer:
            role = "interference_buffer_queen_neighbor"
        else:
            role = "candidate_control_outside_queen_buffer"
        roles[geoid] = {
            "cohort_role": role,
            "event_record_numbers": sorted(treated_events.get(geoid, [])),
            "adjacent_treated_queen_count": len(queen_neighbors[geoid] & treated),
            "adjacent_treated_rook_count": len(rook_neighbors[geoid] & treated),
            "inside_queen_interference_buffer": geoid in queen_buffer,
            "inside_rook_interference_buffer": geoid in rook_buffer,
        }
    return roles


def _validate_race_crosscheck(path: Path) -> dict[str, Any]:
    rows = _read_json_list(path)
    if len(rows) != 5:
        raise ValueError("race_crosscheck_count_mismatch")
    by_permit = {str(row["permit_"]): row for row in rows}
    if by_permit["101063756"].get("census_tract") != "243400":
        raise ValueError("race_current_tract_code_mismatch")
    if {str(row.get("census_tract")) for row in rows} != {"2434", "243400"}:
        raise ValueError("race_mixed_tract_vintage_not_observed")
    return {
        "address": "1228 W RACE AVE",
        "row_count": len(rows),
        "observed_source_tract_values": ["2434", "243400"],
        "current_2020_tract_geoid": "17031243400",
        "post_2020_rows_match_official_crosswalk": True,
        "legacy_rows_require_point_reassignment": True,
    }


def _validate_capture(path: Path) -> dict[str, Any]:
    capture_path = _capture_path(path)
    capture = _read_json(capture_path)
    payload = path.read_bytes()
    if capture.get("schema") != "gwm.chicago_browser_cdp_capture.v1":
        raise ValueError(f"capture_schema_mismatch:{capture_path}")
    if capture.get("http_status") != 200:
        raise ValueError(f"capture_http_status_mismatch:{capture_path}")
    if capture.get("bytes") != len(payload):
        raise ValueError(f"capture_byte_count_mismatch:{capture_path}")
    if capture.get("sha256") != hashlib.sha256(payload).hexdigest():
        raise ValueError(f"capture_hash_mismatch:{capture_path}")
    if capture.get("cookies_or_credentials_persisted") is not False:
        raise ValueError(f"capture_cookie_boundary_mismatch:{capture_path}")
    return capture


def _source_tract_geoid(value: Any, official_geoids: set[str]) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    if not text.isdigit():
        return None
    geoid = COOK_GEOID_PREFIX + str(int(text)).zfill(6)
    return geoid if geoid in official_geoids else None


def _month_sequence(start: date, end_exclusive: date) -> list[str]:
    months = []
    year, month = start.year, start.month
    while (year, month) < (end_exclusive.year, end_exclusive.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def _parse_socrata_date(value: Any) -> date:
    return datetime.fromisoformat(str(value)).date()


def _finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _shapefile_components(shapefile_path: Path) -> list[Path]:
    stem = shapefile_path.with_suffix("")
    suffixes = (
        ".cpg",
        ".dbf",
        ".prj",
        ".shp",
        ".shp.ea.iso.xml",
        ".shp.iso.xml",
        ".shx",
    )
    paths = [Path(f"{stem}{suffix}") for suffix in suffixes]
    if not all(path.is_file() for path in paths):
        raise ValueError(f"shapefile_components_missing:{shapefile_path}")
    return paths


def _capture_path(path: Path) -> Path:
    return Path(f"{path}.capture.json")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json_object_required:{path}")
    return payload


def _read_json_list(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"json_list_required:{path}")
    return payload


def _artifact(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_permit_tract_month_panel()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["assignment_diagnostics"], sort_keys=True))
    print(json.dumps(result["panel_summary"], sort_keys=True))
    print(result["panel_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
