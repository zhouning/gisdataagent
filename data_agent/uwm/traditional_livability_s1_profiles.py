from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from data_agent.uwm.traditional_livability_facility_dictionary import (
    compute_canonical_content_digest,
)


PROFILE_SCHEMA = "uwm.traditional_livability.s1_metric_profile.v1"
MATRIX_SCHEMA = "uwm.traditional_livability.s1_synthesis_matrix.v1"
PROFILE_COLLECTION_SCHEMA = "uwm.traditional_livability.s1_metric_profile_collection.v1"

_DIMENSIONS = {"FP", "FPP"}
_COMPARATORS = {">=", "<=", ">", "<", "=="}
_FP_METHODS = {"euclidean_service_radius", "administrative_subunit_presence", "network_service_area"}
_STATUSES = {"meets", "does_not_meet"}
_SOURCE_FIELDS = {"issuing_organisation", "source_reference", "effective_date", "version"}


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _valid_source_metadata(value: Any) -> bool:
    return isinstance(value, Mapping) and all(_text(value.get(field)) for field in _SOURCE_FIELDS)


def _digest_matches(payload: Mapping[str, Any]) -> bool:
    supplied = _text(payload.get("content_digest"))
    if supplied is None:
        return False
    expected = compute_canonical_content_digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )
    return supplied == expected


def unavailable_s1_metric_profiles() -> dict[str, Any]:
    return {
        "schema": PROFILE_COLLECTION_SCHEMA,
        "status": "unavailable",
        "profiles": [],
        "blockers": ["authoritative_s1_metric_profile_missing"],
    }


def validate_s1_metric_profile(payload: Mapping[str, Any]) -> dict[str, Any]:
    profile = deepcopy(dict(payload)) if isinstance(payload, Mapping) else {}
    blockers: list[str] = []
    if profile.get("schema") != PROFILE_SCHEMA:
        blockers.append("s1_metric_profile_schema_invalid")
    if _text(profile.get("profile_id")) is None:
        blockers.append("profile_id_required")
    if _text(profile.get("standard_class_id")) is None:
        blockers.append("standard_class_id_required")
    if profile.get("authority_level") != "authoritative":
        blockers.append("authoritative_profile_required")
    if not _valid_source_metadata(profile.get("source_metadata")):
        blockers.append("profile_source_metadata_invalid")
    if not _digest_matches(profile):
        blockers.append("profile_content_digest_invalid")

    dimensions = profile.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions or any(value not in _DIMENSIONS for value in dimensions):
        blockers.append("profile_dimensions_invalid")
        dimensions = []
    elif len(set(dimensions)) != len(dimensions):
        blockers.append("profile_dimensions_duplicate")
    if set(dimensions) == _DIMENSIONS and _text(profile.get("synthesis_matrix_id")) is None:
        blockers.append("synthesis_matrix_reference_required")

    metrics = profile.get("metrics")
    if not isinstance(metrics, list):
        blockers.append("profile_metrics_invalid")
        metrics = []
    seen_dimensions = set()
    normalized_metrics = []
    for metric in metrics:
        if not isinstance(metric, Mapping):
            blockers.append("profile_metric_record_invalid")
            continue
        row = deepcopy(dict(metric))
        dimension = row.get("dimension")
        if dimension not in _DIMENSIONS:
            blockers.append("profile_metric_dimension_invalid")
            continue
        if dimension in seen_dimensions:
            blockers.append(f"duplicate_metric_dimension:{dimension}")
        seen_dimensions.add(dimension)
        if _text(row.get("metric")) is None:
            blockers.append(f"metric_name_required:{dimension}")
        if _text(row.get("unit")) is None:
            blockers.append(f"metric_unit_required:{dimension}")
        if row.get("comparator") not in _COMPARATORS:
            blockers.append(f"metric_comparator_invalid:{dimension}")
        if not isinstance(row.get("threshold"), (int, float)) or isinstance(row.get("threshold"), bool):
            blockers.append(f"metric_threshold_invalid:{dimension}")
        fields = row.get("required_source_fields")
        if not isinstance(fields, list) or not fields or any(_text(field) is None for field in fields):
            blockers.append(f"required_source_fields_invalid:{dimension}")
        if dimension == "FP":
            method = row.get("spatial_method")
            if method not in _FP_METHODS:
                blockers.append("fp_spatial_method_invalid")
            elif method == "euclidean_service_radius":
                radius = row.get("service_radius_m")
                if not isinstance(radius, (int, float)) or isinstance(radius, bool) or radius <= 0:
                    blockers.append("authoritative_service_radius_required")
                if _text(row.get("distance_crs")) is None:
                    blockers.append("fp_distance_crs_required")
            elif method == "network_service_area":
                if _text(row.get("network_reference")) is None:
                    blockers.append("authoritative_network_reference_required")
                if _text(row.get("impedance_rule_reference")) is None:
                    blockers.append("authoritative_impedance_rule_required")
        normalized_metrics.append(row)
    missing_dimensions = [dimension for dimension in dimensions if dimension not in seen_dimensions]
    blockers.extend(f"metric_definition_missing:{dimension}" for dimension in missing_dimensions)

    profile["dimensions"] = dimensions
    profile["metrics"] = normalized_metrics
    profile["status"] = "valid" if not blockers else "invalid"
    profile["blockers"] = list(dict.fromkeys(blockers))
    return deepcopy(profile)


def validate_s1_synthesis_matrix(payload: Mapping[str, Any]) -> dict[str, Any]:
    matrix = deepcopy(dict(payload)) if isinstance(payload, Mapping) else {}
    blockers: list[str] = []
    if matrix.get("schema") != MATRIX_SCHEMA:
        blockers.append("synthesis_matrix_schema_invalid")
    if _text(matrix.get("matrix_id")) is None:
        blockers.append("synthesis_matrix_id_required")
    if matrix.get("authority_level") != "authoritative":
        blockers.append("authoritative_synthesis_matrix_required")
    if not _valid_source_metadata(matrix.get("source_metadata")):
        blockers.append("synthesis_matrix_source_metadata_invalid")
    if not _digest_matches(matrix):
        blockers.append("synthesis_matrix_content_digest_invalid")
    outcomes = matrix.get("outcomes")
    normalized = []
    pairs = set()
    if not isinstance(outcomes, list):
        blockers.append("synthesis_matrix_outcomes_invalid")
        outcomes = []
    for outcome in outcomes:
        if not isinstance(outcome, Mapping):
            blockers.append("synthesis_matrix_outcome_invalid")
            continue
        row = deepcopy(dict(outcome))
        pair = (row.get("fp_status"), row.get("fpp_status"))
        if pair[0] not in _STATUSES or pair[1] not in _STATUSES:
            blockers.append("synthesis_matrix_dimension_status_invalid")
            continue
        if row.get("combined_status") not in _STATUSES:
            blockers.append("synthesis_matrix_combined_status_invalid")
        if pair in pairs:
            blockers.append("synthesis_matrix_pair_duplicate")
        pairs.add(pair)
        normalized.append(row)
    expected = {(fp, fpp) for fp in _STATUSES for fpp in _STATUSES}
    if pairs != expected:
        blockers.append("synthesis_matrix_incomplete")
    matrix["outcomes"] = normalized
    matrix["status"] = "valid" if not blockers else "invalid"
    matrix["blockers"] = list(dict.fromkeys(blockers))
    return deepcopy(matrix)
