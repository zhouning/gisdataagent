"""Internal freeze contract for the next observed-station P1 evaluation."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from ..geospatial_state_prior_benchmark import REQUIRED_GEOMETRY_ROUTES, REQUIRED_SPLITS

STATE_PRIOR_P1_PROSPECTIVE_PROTOCOL_SCHEMA = (
    "uwm.geospatial_kernel.state_prior_p1_prospective_protocol.v1"
)

_CANDIDATE = "multi_geometry_soft_alignment_ridge"
_BASELINES = (
    "spatial_idw",
    "hard_admin_mean",
    "raster_only_ridge",
    "raster_admin_soft_alignment_ridge",
)
_NEGATIVE_CONTROLS = (
    "shuffled_admin_alignment_ridge",
    "shuffled_graph_alignment_ridge",
)
_MINIMUM_SUPPORT_FLOORS = {
    "minimum_rows": 60,
    "minimum_stations": 10,
    "minimum_admin_groups": 10,
    "minimum_time_groups": 6,
    "minimum_spatial_bands": 10,
}
_CONFIDENCE_LEVEL = 0.9
_COVERAGE_TOLERANCE = 0.05
_MINIMUM_RELATIVE_IMPROVEMENT = 0.01
_NEGATIVE_CONTROL_SEED = 37
_ACTIVATION_GATES = (
    "external_registration_receipt_verified",
    "holdout_access_log_available",
    "eligible_source_artifacts_acquired_and_hashed",
    "minimum_support_verified",
    "admin_boundary_vintage_verified",
    "source_license_and_lineage_verified",
    "p1_input_readiness_reassessed",
)
_CLAIM_BOUNDARY = {
    "max_claim_level": "not_for_claim",
    "scope": "internal_protocol_freeze_only",
    "external_preregistration_verified": False,
    "holdout_blinding_independently_verified": False,
    "p1_execution_permitted": False,
    "p2_admission_permitted": False,
    "scientific_result_claim": False,
    "transition_skill_improvement_claim": False,
    "policy_causal_effect_claim": False,
    "general_geospatial_world_model_validation_claim": False,
}


def build_state_prior_p1_prospective_protocol(
    *,
    protocol_id: str,
    created_at: str,
    frozen_at: str,
    prior_diagnostic_sha256: str,
    development_window: Mapping[str, str],
    final_holdout_window: Mapping[str, str],
    eligible_feature_sources: Mapping[str, Mapping[str, Any]],
    evidence_refs: Sequence[str],
    minimum_rows: int = 60,
    minimum_stations: int = 10,
    minimum_admin_groups: int = 10,
    minimum_time_groups: int = 6,
    minimum_spatial_bands: int = 10,
    confidence_level: float = 0.9,
    coverage_tolerance: float = 0.05,
    minimum_relative_improvement: float = 0.01,
    negative_control_seed: int = 37,
) -> dict[str, Any]:
    """Freeze choices for a fresh P1 period while keeping execution disabled."""

    if not _nonempty_string(protocol_id):
        raise ValueError("state_prior_p1_prospective_protocol_id_required")
    created = _require_aware_timestamp(created_at, "created_at")
    frozen = _require_aware_timestamp(frozen_at, "frozen_at")
    if created > frozen:
        raise ValueError("state_prior_p1_prospective_protocol_frozen_before_creation")
    if not _valid_sha256(prior_diagnostic_sha256):
        raise ValueError("state_prior_p1_prospective_prior_diagnostic_sha256_invalid")
    development = _normalize_window(development_window, "development_window")
    final_holdout = _normalize_window(final_holdout_window, "final_holdout_window")
    if development["end_date"] >= final_holdout["start_date"]:
        raise ValueError("state_prior_p1_prospective_windows_overlap_or_out_of_order")
    sources = _normalize_sources(eligible_feature_sources)
    refs = _unique_nonempty_strings(evidence_refs)
    support = {
        "minimum_rows": _positive_int(minimum_rows, "minimum_rows"),
        "minimum_stations": _positive_int(minimum_stations, "minimum_stations"),
        "minimum_admin_groups": _positive_int(minimum_admin_groups, "minimum_admin_groups"),
        "minimum_time_groups": _positive_int(minimum_time_groups, "minimum_time_groups"),
        "minimum_spatial_bands": _positive_int(minimum_spatial_bands, "minimum_spatial_bands"),
    }
    for field, floor in _MINIMUM_SUPPORT_FLOORS.items():
        if support[field] < floor:
            raise ValueError(f"state_prior_p1_prospective_{field}_below_frozen_floor")
    if confidence_level != _CONFIDENCE_LEVEL:
        raise ValueError("state_prior_p1_prospective_confidence_level_must_remain_frozen")
    if coverage_tolerance != _COVERAGE_TOLERANCE:
        raise ValueError("state_prior_p1_prospective_coverage_tolerance_must_remain_frozen")
    if minimum_relative_improvement != _MINIMUM_RELATIVE_IMPROVEMENT:
        raise ValueError("state_prior_p1_prospective_improvement_threshold_must_remain_frozen")
    if negative_control_seed != _NEGATIVE_CONTROL_SEED:
        raise ValueError("state_prior_p1_prospective_negative_control_seed_must_remain_frozen")

    protocol = {
        "schema": STATE_PRIOR_P1_PROSPECTIVE_PROTOCOL_SCHEMA,
        "version": "0.1",
        "protocol_id": str(protocol_id),
        "created_at": str(created_at),
        "frozen_at": str(frozen_at),
        "prior_failure_diagnostic_sha256": prior_diagnostic_sha256,
        "window_design": {
            "development_window": {
                **development,
                "role": "opened_posthoc_development_only",
                "eligible_for_scientific_claim": False,
            },
            "final_holdout_window": {
                **final_holdout,
                "role": "fresh_target_acquisition_and_final_evaluation",
                "target_access_status_at_internal_freeze": "not_acquired_by_protocol_builder",
            },
            "windows_non_overlapping": True,
            "development_results_cannot_satisfy_final_holdout_gates": True,
        },
        "eligible_feature_sources": sources,
        "feature_freeze": {
            "required_geometry_routes": list(REQUIRED_GEOMETRY_ROUTES),
            "source_allowlist_closed": True,
            "undeclared_features_prohibited": True,
            "target_derived_features_prohibited": True,
            "same_day_target_proxy_features_prohibited": True,
            "feature_selection_after_development_diagnostic_prohibited": True,
            "feature_selection_after_final_holdout_access_prohibited": True,
        },
        "minimum_support": support,
        "evaluation_design": {
            "required_splits": list(REQUIRED_SPLITS),
            "candidate_method": _CANDIDATE,
            "required_baselines": list(_BASELINES),
            "negative_controls": list(_NEGATIVE_CONTROLS),
            "model_class": "deterministic_standardized_ridge",
            "confidence_level": float(confidence_level),
            "coverage_tolerance": float(coverage_tolerance),
            "minimum_coverage_threshold": float(confidence_level - coverage_tolerance),
            "minimum_relative_improvement": float(minimum_relative_improvement),
            "negative_control_seed": negative_control_seed,
            "candidate_must_beat_every_required_baseline_on_every_split": True,
            "both_geometry_shuffle_controls_must_pass": True,
            "split_conformal_coverage_must_pass": True,
            "threshold_changes_after_freeze_prohibited": True,
        },
        "activation_gates": {gate: False for gate in _ACTIVATION_GATES},
        "evidence_refs": refs,
        "p1_execution_permitted": False,
        "p2_admission_permitted": False,
        "supported_claim": "internally_frozen_next_p1_protocol_only",
        "claim_boundary": copy.deepcopy(_CLAIM_BOUNDARY),
    }
    protocol["protocol_sha256"] = compute_state_prior_p1_prospective_protocol_sha256(protocol)
    validation = validate_state_prior_p1_prospective_protocol(protocol)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_p1_prospective_protocol:" + ";".join(validation["errors"])
        )
    return protocol


def validate_state_prior_p1_prospective_protocol(payload: Any) -> dict[str, Any]:
    """Validate an internal freeze without treating it as external preregistration."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["p1_prospective_protocol_must_be_dictionary"]}
    errors: list[str] = []
    expected_fields = {
        "schema",
        "version",
        "protocol_id",
        "created_at",
        "frozen_at",
        "prior_failure_diagnostic_sha256",
        "window_design",
        "eligible_feature_sources",
        "feature_freeze",
        "minimum_support",
        "evaluation_design",
        "activation_gates",
        "evidence_refs",
        "p1_execution_permitted",
        "p2_admission_permitted",
        "supported_claim",
        "claim_boundary",
        "protocol_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("p1_prospective_protocol_field_set_mismatch")
    if payload.get("schema") != STATE_PRIOR_P1_PROSPECTIVE_PROTOCOL_SCHEMA:
        errors.append("p1_prospective_protocol_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("p1_prospective_protocol_version_mismatch")
    for field in ("protocol_id", "created_at", "frozen_at"):
        if not _nonempty_string(payload.get(field)):
            errors.append(f"p1_prospective_protocol_{field}_required")
    created = _parse_aware_timestamp(payload.get("created_at"))
    frozen = _parse_aware_timestamp(payload.get("frozen_at"))
    if created is None:
        errors.append("p1_prospective_protocol_created_at_invalid")
    if frozen is None:
        errors.append("p1_prospective_protocol_frozen_at_invalid")
    if created is not None and frozen is not None and created > frozen:
        errors.append("p1_prospective_protocol_chronology_invalid")
    if not _valid_sha256(payload.get("prior_failure_diagnostic_sha256")):
        errors.append("p1_prospective_protocol_prior_diagnostic_sha256_invalid")
    _validate_window_design(payload.get("window_design"), errors)
    sources = payload.get("eligible_feature_sources")
    if not isinstance(sources, dict) or tuple(sources) != (
        "target",
        *REQUIRED_GEOMETRY_ROUTES,
    ):
        errors.append("p1_prospective_protocol_feature_sources_invalid")
    else:
        for route, source in sources.items():
            if not isinstance(source, dict):
                errors.append(f"p1_prospective_protocol_{route}_source_invalid")
                continue
            if set(source) != {
                "source_id",
                "source_role",
                "feature_names",
                "temporal_rule",
                "uses_target_values",
                "limitations",
            }:
                errors.append(f"p1_prospective_protocol_{route}_source_fields_invalid")
            if not _nonempty_string(source.get("source_id")) or not _nonempty_string(
                source.get("source_role")
            ):
                errors.append(f"p1_prospective_protocol_{route}_source_id_invalid")
            if source.get("uses_target_values") is not False:
                errors.append(f"p1_prospective_protocol_{route}_source_target_boundary_invalid")
            features = source.get("feature_names")
            if (
                not isinstance(features, list)
                or not features
                or features != _unique_nonempty_strings(features)
            ):
                errors.append(f"p1_prospective_protocol_{route}_features_invalid")
            if not _nonempty_string(source.get("temporal_rule")):
                errors.append(f"p1_prospective_protocol_{route}_temporal_rule_invalid")
            limitations = source.get("limitations")
            if not isinstance(limitations, list) or limitations != _unique_nonempty_strings(
                limitations
            ):
                errors.append(f"p1_prospective_protocol_{route}_limitations_invalid")
    expected_freeze = {
        "required_geometry_routes": list(REQUIRED_GEOMETRY_ROUTES),
        "source_allowlist_closed": True,
        "undeclared_features_prohibited": True,
        "target_derived_features_prohibited": True,
        "same_day_target_proxy_features_prohibited": True,
        "feature_selection_after_development_diagnostic_prohibited": True,
        "feature_selection_after_final_holdout_access_prohibited": True,
    }
    if payload.get("feature_freeze") != expected_freeze:
        errors.append("p1_prospective_protocol_feature_freeze_invalid")
    support = payload.get("minimum_support")
    if not isinstance(support, dict) or set(support) != {
        "minimum_rows",
        "minimum_stations",
        "minimum_admin_groups",
        "minimum_time_groups",
        "minimum_spatial_bands",
    }:
        errors.append("p1_prospective_protocol_minimum_support_invalid")
    elif any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in support.values()
    ):
        errors.append("p1_prospective_protocol_minimum_support_values_invalid")
    elif any(support[field] < floor for field, floor in _MINIMUM_SUPPORT_FLOORS.items()):
        errors.append("p1_prospective_protocol_minimum_support_below_frozen_floor")
    _validate_evaluation_design(payload.get("evaluation_design"), errors)
    gates = payload.get("activation_gates")
    if (
        not isinstance(gates, dict)
        or tuple(gates) != _ACTIVATION_GATES
        or any(value is not False for value in gates.values())
    ):
        errors.append("p1_prospective_protocol_activation_gates_must_start_false")
    refs = payload.get("evidence_refs")
    if not isinstance(refs, list) or not refs or refs != _unique_nonempty_strings(refs):
        errors.append("p1_prospective_protocol_evidence_refs_invalid")
    if payload.get("p1_execution_permitted") is not False:
        errors.append("p1_prospective_protocol_cannot_self_authorize_execution")
    if payload.get("p2_admission_permitted") is not False:
        errors.append("p1_prospective_protocol_cannot_permit_p2_admission")
    if payload.get("supported_claim") != "internally_frozen_next_p1_protocol_only":
        errors.append("p1_prospective_protocol_supported_claim_invalid")
    if payload.get("claim_boundary") != _CLAIM_BOUNDARY:
        errors.append("p1_prospective_protocol_claim_boundary_invalid")
    digest = payload.get("protocol_sha256")
    if not _valid_sha256(digest):
        errors.append("p1_prospective_protocol_sha256_invalid")
    elif digest != compute_state_prior_p1_prospective_protocol_sha256(payload):
        errors.append("p1_prospective_protocol_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def compute_state_prior_p1_prospective_protocol_sha256(
    payload: Mapping[str, Any],
) -> str:
    """Compute the canonical digest for the prospective P1 protocol."""

    values = copy.deepcopy(dict(payload))
    values.pop("protocol_sha256", None)
    return _canonical_sha256(values)


def _normalize_window(value: Mapping[str, str], field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"start_date", "end_date"}:
        raise ValueError(f"state_prior_p1_prospective_{field}_invalid")
    try:
        start = date.fromisoformat(str(value["start_date"]))
        end = date.fromisoformat(str(value["end_date"]))
    except ValueError as exc:
        raise ValueError(f"state_prior_p1_prospective_{field}_invalid") from exc
    if start > end:
        raise ValueError(f"state_prior_p1_prospective_{field}_invalid")
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def _normalize_sources(
    sources: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    expected = ("target", *REQUIRED_GEOMETRY_ROUTES)
    if not isinstance(sources, Mapping) or tuple(sources) != expected:
        raise ValueError("state_prior_p1_prospective_feature_sources_invalid")
    normalized: dict[str, dict[str, Any]] = {}
    for route in expected:
        source = sources[route]
        if not isinstance(source, Mapping):
            raise ValueError(f"state_prior_p1_prospective_{route}_source_invalid")
        required = {
            "source_id",
            "source_role",
            "feature_names",
            "temporal_rule",
            "uses_target_values",
            "limitations",
        }
        if set(source) != required:
            raise ValueError(f"state_prior_p1_prospective_{route}_source_fields_invalid")
        if not _nonempty_string(source.get("source_id")) or not _nonempty_string(
            source.get("source_role")
        ):
            raise ValueError(f"state_prior_p1_prospective_{route}_source_id_invalid")
        features = source.get("feature_names")
        if (
            not isinstance(features, list)
            or not features
            or features != _unique_nonempty_strings(features)
        ):
            raise ValueError(f"state_prior_p1_prospective_{route}_features_invalid")
        if not _nonempty_string(source.get("temporal_rule")):
            raise ValueError(f"state_prior_p1_prospective_{route}_temporal_rule_invalid")
        if source.get("uses_target_values") is not False:
            raise ValueError(f"state_prior_p1_prospective_{route}_uses_target_values_invalid")
        limitations = source.get("limitations")
        if not isinstance(limitations, list) or limitations != _unique_nonempty_strings(
            limitations
        ):
            raise ValueError(f"state_prior_p1_prospective_{route}_limitations_invalid")
        normalized[route] = copy.deepcopy(dict(source))
    return normalized


def _validate_window_design(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("p1_prospective_protocol_window_design_invalid")
        return
    development = value.get("development_window") or {}
    final_holdout = value.get("final_holdout_window") or {}
    try:
        normalized_development = _normalize_window(
            {
                "start_date": development.get("start_date"),
                "end_date": development.get("end_date"),
            },
            "development_window",
        )
        normalized_holdout = _normalize_window(
            {
                "start_date": final_holdout.get("start_date"),
                "end_date": final_holdout.get("end_date"),
            },
            "final_holdout_window",
        )
    except ValueError:
        errors.append("p1_prospective_protocol_window_dates_invalid")
        return
    if normalized_development["end_date"] >= normalized_holdout["start_date"]:
        errors.append("p1_prospective_protocol_windows_overlap_or_out_of_order")
    if development.get("role") != "opened_posthoc_development_only":
        errors.append("p1_prospective_protocol_development_role_invalid")
    if development.get("eligible_for_scientific_claim") is not False:
        errors.append("p1_prospective_protocol_development_claim_boundary_invalid")
    if final_holdout.get("role") != "fresh_target_acquisition_and_final_evaluation":
        errors.append("p1_prospective_protocol_final_holdout_role_invalid")
    if (
        final_holdout.get("target_access_status_at_internal_freeze")
        != "not_acquired_by_protocol_builder"
    ):
        errors.append("p1_prospective_protocol_target_access_status_invalid")
    if value.get("windows_non_overlapping") is not True:
        errors.append("p1_prospective_protocol_non_overlap_assertion_invalid")
    if value.get("development_results_cannot_satisfy_final_holdout_gates") is not True:
        errors.append("p1_prospective_protocol_development_gate_boundary_invalid")


def _validate_evaluation_design(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("p1_prospective_protocol_evaluation_design_invalid")
        return
    if value.get("required_splits") != list(REQUIRED_SPLITS):
        errors.append("p1_prospective_protocol_required_splits_invalid")
    if value.get("candidate_method") != _CANDIDATE:
        errors.append("p1_prospective_protocol_candidate_invalid")
    if value.get("required_baselines") != list(_BASELINES):
        errors.append("p1_prospective_protocol_baselines_invalid")
    if value.get("negative_controls") != list(_NEGATIVE_CONTROLS):
        errors.append("p1_prospective_protocol_negative_controls_invalid")
    if value.get("model_class") != "deterministic_standardized_ridge":
        errors.append("p1_prospective_protocol_model_class_invalid")
    confidence = value.get("confidence_level")
    tolerance = value.get("coverage_tolerance")
    threshold = value.get("minimum_coverage_threshold")
    if confidence != _CONFIDENCE_LEVEL:
        errors.append("p1_prospective_protocol_confidence_level_invalid")
    if tolerance != _COVERAGE_TOLERANCE:
        errors.append("p1_prospective_protocol_coverage_tolerance_invalid")
    if (
        isinstance(confidence, (int, float))
        and isinstance(tolerance, (int, float))
        and float(tolerance) >= float(confidence)
    ):
        errors.append("p1_prospective_protocol_coverage_tolerance_exceeds_confidence")
    if (
        isinstance(confidence, (int, float))
        and isinstance(tolerance, (int, float))
        and threshold != confidence - tolerance
    ):
        errors.append("p1_prospective_protocol_coverage_threshold_mismatch")
    if value.get("minimum_relative_improvement") != _MINIMUM_RELATIVE_IMPROVEMENT:
        errors.append("p1_prospective_protocol_improvement_threshold_invalid")
    seed = value.get("negative_control_seed")
    if seed != _NEGATIVE_CONTROL_SEED:
        errors.append("p1_prospective_protocol_negative_control_seed_invalid")
    for field in (
        "candidate_must_beat_every_required_baseline_on_every_split",
        "both_geometry_shuffle_controls_must_pass",
        "split_conformal_coverage_must_pass",
        "threshold_changes_after_freeze_prohibited",
    ):
        if value.get(field) is not True:
            errors.append(f"p1_prospective_protocol_{field}_must_be_true")


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"state_prior_p1_prospective_{field}_invalid")
    return value


def _unique_nonempty_strings(values: Sequence[Any]) -> list[str]:
    if isinstance(values, (str, bytes)):
        return []
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not _nonempty_string(value):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _require_aware_timestamp(value: Any, field: str) -> datetime:
    parsed = _parse_aware_timestamp(value)
    if parsed is None:
        raise ValueError(f"state_prior_p1_prospective_{field}_invalid")
    return parsed
