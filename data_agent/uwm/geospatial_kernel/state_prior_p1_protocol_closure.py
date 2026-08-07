"""Fail-closed closure for an unusable frozen state-prior P1 protocol."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from .state_prior_p1_prospective_protocol import (
    validate_state_prior_p1_prospective_protocol,
)
from .state_prior_predictor_preflight import validate_state_prior_predictor_preflight

STATE_PRIOR_P1_PROTOCOL_CLOSURE_SCHEMA = "uwm.geospatial_kernel.state_prior_p1_protocol_closure.v1"

_CLOSURE_REASONS = [
    "frozen_admin_source_vintage_unverified",
    "frozen_admin_source_license_unverified",
    "closed_source_allowlist_prohibits_geofabrik_substitution",
    "geofabrik_probe_is_post_holdout_topology_metadata_not_admin_snapshot",
]
_V2_REENTRY_REQUIREMENTS = [
    "new_protocol_digest_created_before_target_acquisition",
    "external_registration_receipt_verified_before_target_acquisition",
    "admin_source_identity_and_authority_or_proxy_status_declared",
    "admin_snapshot_capture_or_effective_date_not_after_predictor_cutoff",
    "admin_source_url_license_and_content_sha256_verified",
    "administrative_geometry_extracted_and_geometry_sha256_verified",
    "geometry_validity_crs_coverage_and_topology_verified",
    "station_crosswalk_and_admin_graph_rebuilt_from_the_same_snapshot",
    "all_predictor_and_minimum_support_gates_reassessed",
    "target_access_log_still_empty_at_external_registration",
]
_CLAIM_BOUNDARY = {
    "max_claim_level": "not_for_claim",
    "scope": "frozen_protocol_fail_closed_retirement_only",
    "observed_target_claim": False,
    "p1_result_claim": False,
    "p2_admission_permitted": False,
    "scientific_result_claim": False,
    "general_geospatial_world_model_validation_claim": False,
}


def build_state_prior_p1_protocol_closure(
    *,
    closure_id: str,
    created_at: str,
    protocol: Mapping[str, Any],
    predictor_preflight: Mapping[str, Any],
    acquisition_plan: Mapping[str, Any],
    prior_attempt_manifest: Mapping[str, Any],
    geofabrik_probe_report: Mapping[str, Any],
    evidence_refs: Sequence[str],
) -> dict[str, Any]:
    """Retire one protocol digest without acquiring or inspecting its final target."""

    if not _nonempty_string(closure_id):
        raise ValueError("state_prior_p1_protocol_closure_id_required")
    _require_aware_timestamp(created_at)
    protocol_payload = copy.deepcopy(dict(protocol))
    preflight = copy.deepcopy(dict(predictor_preflight))
    plan = copy.deepcopy(dict(acquisition_plan))
    prior_attempt = copy.deepcopy(dict(prior_attempt_manifest))
    probe_report = copy.deepcopy(dict(geofabrik_probe_report))
    refs = _unique_nonempty_strings(evidence_refs)
    if not refs:
        raise ValueError("state_prior_p1_protocol_closure_evidence_refs_required")

    protocol_validation = validate_state_prior_p1_prospective_protocol(protocol_payload)
    if not protocol_validation["valid"]:
        raise ValueError(
            "state_prior_p1_protocol_closure_protocol_invalid:"
            + ";".join(protocol_validation["errors"])
        )
    preflight_validation = validate_state_prior_predictor_preflight(preflight)
    if not preflight_validation["valid"]:
        raise ValueError(
            "state_prior_p1_protocol_closure_preflight_invalid:"
            + ";".join(preflight_validation["errors"])
        )
    if preflight.get("protocol_id") != protocol_payload.get("protocol_id") or preflight.get(
        "protocol_sha256"
    ) != protocol_payload.get("protocol_sha256"):
        raise ValueError("state_prior_p1_protocol_closure_protocol_binding_mismatch")
    if not _valid_acquisition_plan(plan):
        raise ValueError("state_prior_p1_protocol_closure_acquisition_plan_invalid")
    if plan.get("measurement_downloaded") is not False:
        raise ValueError("state_prior_p1_protocol_closure_requires_unacquired_plan")
    if not _prior_attempt_has_no_target(prior_attempt):
        raise ValueError("state_prior_p1_protocol_closure_prior_attempt_exposed_target")
    if (preflight.get("activation_blockers") or {}).get(
        "target_measurements_acquired"
    ) is not False:
        raise ValueError("state_prior_p1_protocol_closure_preflight_exposed_target")

    feature_freeze = protocol_payload["feature_freeze"]
    frozen_admin = protocol_payload["eligible_feature_sources"]["admin"]
    admin_provenance = preflight["admin_provenance_audit"]
    if feature_freeze.get("source_allowlist_closed") is not True:
        raise ValueError("state_prior_p1_protocol_closure_requires_closed_source_allowlist")
    if admin_provenance.get("official_boundary_vintage_verified") is not False:
        raise ValueError("state_prior_p1_protocol_closure_requires_unverified_admin_vintage")
    if admin_provenance.get("source_license_verified") is not False:
        raise ValueError("state_prior_p1_protocol_closure_requires_unverified_admin_license")

    final_window = protocol_payload["window_design"]["final_holdout_window"]
    target_start = date.fromisoformat(str(final_window["start_date"]))
    target_end = date.fromisoformat(str(final_window["end_date"]))
    geofabrik = _geofabrik_candidate_audit(
        report=probe_report,
        frozen_admin_source_id=str(frozen_admin["source_id"]),
        target_start=target_start,
        target_end=target_end,
    )
    if geofabrik["eligible_as_frozen_protocol_repair"] is not False:
        raise ValueError("state_prior_p1_protocol_closure_geofabrik_unexpectedly_admissible")

    closure = {
        "schema": STATE_PRIOR_P1_PROTOCOL_CLOSURE_SCHEMA,
        "version": "0.1",
        "closure_id": str(closure_id),
        "created_at": str(created_at),
        "protocol_binding": {
            "protocol_id": protocol_payload["protocol_id"],
            "protocol_sha256": protocol_payload["protocol_sha256"],
            "source_allowlist_closed": True,
            "frozen_admin_source_id": frozen_admin["source_id"],
            "final_holdout_window": {
                "start_date": target_start.isoformat(),
                "end_date": target_end.isoformat(),
            },
        },
        "input_artifact_sha256": {
            "predictor_preflight_sha256": preflight["preflight_sha256"],
            "acquisition_plan_sha256": plan["plan_sha256"],
            "prior_attempt_manifest_sha256": _canonical_sha256(prior_attempt),
            "geofabrik_probe_report_sha256": _canonical_sha256(probe_report),
        },
        "target_access_audit": {
            "scope": "available_local_evidence_only",
            "acquisition_plan_measurement_downloaded": False,
            "prior_attempt_measurement_count": 0,
            "prior_attempt_observed_start": None,
            "prior_attempt_observed_end": None,
            "preflight_target_measurements_acquired": False,
            "target_values_inspected_by_closure_builder": False,
            "target_unconsumed_under_available_evidence": True,
        },
        "frozen_admin_source_audit": {
            "source_id": frozen_admin["source_id"],
            "source_role": frozen_admin["source_role"],
            "local_source_ref": admin_provenance.get("local_source_ref"),
            "metadata_created_date": admin_provenance.get("metadata_created_date"),
            "external_source_url_present": admin_provenance.get("external_source_url_present"),
            "license_document_present": admin_provenance.get("license_document_present"),
            "official_boundary_vintage_verified": False,
            "source_license_verified": False,
            "admissible_under_frozen_protocol": False,
        },
        "replacement_candidate_audit": {
            "geofabrik_chongqing": geofabrik,
            "any_admissible_repair_for_frozen_protocol": False,
        },
        "closure_decision": {
            "status": "closed_fail_closed",
            "closure_reasons": list(_CLOSURE_REASONS),
            "irreversible_for_bound_protocol_digest": True,
            "protocol_reactivation_permitted": False,
            "in_place_source_substitution_permitted": False,
            "replacement_protocol_required": True,
            "target_acquisition_permitted": False,
            "p1_execution_permitted": False,
            "p2_admission_permitted": False,
        },
        "v2_reentry_requirements": list(_V2_REENTRY_REQUIREMENTS),
        "evidence_refs": refs,
        "supported_claim": "frozen_protocol_retired_without_target_acquisition",
        "claim_boundary": copy.deepcopy(_CLAIM_BOUNDARY),
    }
    closure["closure_sha256"] = compute_state_prior_p1_protocol_closure_sha256(closure)
    validation = validate_state_prior_p1_protocol_closure(closure)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_p1_protocol_closure:" + ";".join(validation["errors"])
        )
    return closure


def validate_state_prior_p1_protocol_closure(payload: Any) -> dict[str, Any]:
    """Validate closure integrity and prohibit reopening the bound protocol."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["p1_protocol_closure_must_be_dictionary"]}
    errors: list[str] = []
    expected_fields = {
        "schema",
        "version",
        "closure_id",
        "created_at",
        "protocol_binding",
        "input_artifact_sha256",
        "target_access_audit",
        "frozen_admin_source_audit",
        "replacement_candidate_audit",
        "closure_decision",
        "v2_reentry_requirements",
        "evidence_refs",
        "supported_claim",
        "claim_boundary",
        "closure_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("p1_protocol_closure_field_set_mismatch")
    if payload.get("schema") != STATE_PRIOR_P1_PROTOCOL_CLOSURE_SCHEMA:
        errors.append("p1_protocol_closure_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("p1_protocol_closure_version_mismatch")
    if not _nonempty_string(payload.get("closure_id")):
        errors.append("p1_protocol_closure_id_required")
    if _parse_aware_timestamp(payload.get("created_at")) is None:
        errors.append("p1_protocol_closure_created_at_invalid")

    binding = payload.get("protocol_binding")
    if not isinstance(binding, dict) or set(binding) != {
        "protocol_id",
        "protocol_sha256",
        "source_allowlist_closed",
        "frozen_admin_source_id",
        "final_holdout_window",
    }:
        errors.append("p1_protocol_closure_protocol_binding_invalid")
    elif (
        not _nonempty_string(binding.get("protocol_id"))
        or not _valid_sha256(binding.get("protocol_sha256"))
        or binding.get("source_allowlist_closed") is not True
        or not _nonempty_string(binding.get("frozen_admin_source_id"))
    ):
        errors.append("p1_protocol_closure_protocol_binding_values_invalid")

    hashes = payload.get("input_artifact_sha256")
    if not isinstance(hashes, dict) or set(hashes) != {
        "predictor_preflight_sha256",
        "acquisition_plan_sha256",
        "prior_attempt_manifest_sha256",
        "geofabrik_probe_report_sha256",
    }:
        errors.append("p1_protocol_closure_input_hashes_invalid")
    elif any(not _valid_sha256(value) for value in hashes.values()):
        errors.append("p1_protocol_closure_input_hash_invalid")

    target = payload.get("target_access_audit")
    expected_target = {
        "scope": "available_local_evidence_only",
        "acquisition_plan_measurement_downloaded": False,
        "prior_attempt_measurement_count": 0,
        "prior_attempt_observed_start": None,
        "prior_attempt_observed_end": None,
        "preflight_target_measurements_acquired": False,
        "target_values_inspected_by_closure_builder": False,
        "target_unconsumed_under_available_evidence": True,
    }
    if target != expected_target:
        errors.append("p1_protocol_closure_target_access_audit_invalid")

    admin = payload.get("frozen_admin_source_audit")
    if not isinstance(admin, dict) or any(
        admin.get(field) is not False
        for field in (
            "official_boundary_vintage_verified",
            "source_license_verified",
            "admissible_under_frozen_protocol",
        )
    ):
        errors.append("p1_protocol_closure_frozen_admin_audit_invalid")

    candidates = payload.get("replacement_candidate_audit")
    geofabrik = candidates.get("geofabrik_chongqing") if isinstance(candidates, dict) else None
    if (
        not isinstance(candidates, dict)
        or set(candidates)
        != {
            "geofabrik_chongqing",
            "any_admissible_repair_for_frozen_protocol",
        }
        or candidates.get("any_admissible_repair_for_frozen_protocol") is not False
        or not isinstance(geofabrik, dict)
        or geofabrik.get("eligible_as_frozen_protocol_repair") is not False
    ):
        errors.append("p1_protocol_closure_replacement_audit_invalid")

    expected_decision = {
        "status": "closed_fail_closed",
        "closure_reasons": list(_CLOSURE_REASONS),
        "irreversible_for_bound_protocol_digest": True,
        "protocol_reactivation_permitted": False,
        "in_place_source_substitution_permitted": False,
        "replacement_protocol_required": True,
        "target_acquisition_permitted": False,
        "p1_execution_permitted": False,
        "p2_admission_permitted": False,
    }
    if payload.get("closure_decision") != expected_decision:
        errors.append("p1_protocol_closure_decision_invalid")
    if payload.get("v2_reentry_requirements") != _V2_REENTRY_REQUIREMENTS:
        errors.append("p1_protocol_closure_v2_reentry_requirements_invalid")
    refs = payload.get("evidence_refs")
    if not isinstance(refs, list) or not refs or refs != _unique_nonempty_strings(refs):
        errors.append("p1_protocol_closure_evidence_refs_invalid")
    if payload.get("supported_claim") != "frozen_protocol_retired_without_target_acquisition":
        errors.append("p1_protocol_closure_supported_claim_invalid")
    if payload.get("claim_boundary") != _CLAIM_BOUNDARY:
        errors.append("p1_protocol_closure_claim_boundary_invalid")
    digest = payload.get("closure_sha256")
    if not _valid_sha256(digest):
        errors.append("p1_protocol_closure_sha256_invalid")
    elif digest != compute_state_prior_p1_protocol_closure_sha256(payload):
        errors.append("p1_protocol_closure_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def compute_state_prior_p1_protocol_closure_sha256(payload: Mapping[str, Any]) -> str:
    values = copy.deepcopy(dict(payload))
    values.pop("closure_sha256", None)
    return _canonical_sha256(values)


def _geofabrik_candidate_audit(
    *,
    report: Mapping[str, Any],
    frozen_admin_source_id: str,
    target_start: date,
    target_end: date,
) -> dict[str, Any]:
    probe = (report.get("probes") or {}).get("geofabrik_chongqing_topology") or {}
    last_modified = _parse_http_timestamp(probe.get("last_modified"))
    snapshot_date = last_modified.date() if last_modified is not None else None
    snapshot_not_after_predictor_cutoff = snapshot_date is not None and snapshot_date < target_start
    return {
        "candidate_id": "geofabrik_chongqing_osm_extract",
        "probe_status": probe.get("status"),
        "region_id": probe.get("region_id"),
        "canonical_pbf_url": probe.get("pbf_url"),
        "resolved_snapshot_url": probe.get("final_url"),
        "content_length": probe.get("content_length"),
        "last_modified": probe.get("last_modified"),
        "snapshot_date": snapshot_date.isoformat() if snapshot_date is not None else None,
        "final_holdout_end_date": target_end.isoformat(),
        "snapshot_not_after_predictor_cutoff": snapshot_not_after_predictor_cutoff,
        "frozen_source_id_match": "geofabrik" in frozen_admin_source_id.lower(),
        "administrative_boundary_extract_present": False,
        "administrative_geometry_sha256_present": False,
        "geometry_validity_verified": False,
        "official_boundary_source_verified": False,
        "license_evidence_attached_to_probe": False,
        "download_performed": probe.get("download_performed"),
        "evidence_status": probe.get("evidence_status"),
        "eligible_as_frozen_protocol_repair": False,
        "rejection_reasons": [
            "candidate_not_in_closed_source_allowlist",
            "resolved_snapshot_is_after_predictor_cutoff",
            "probe_contains_topology_metadata_not_extracted_admin_geometry",
            "official_boundary_status_not_verified",
            "license_evidence_not_attached_to_probe",
        ],
    }


def _valid_acquisition_plan(plan: Mapping[str, Any]) -> bool:
    if plan.get("schema") != "uwm.openaq_multi_station_acquisition_plan.v1":
        return False
    digest = plan.get("plan_sha256")
    values = copy.deepcopy(dict(plan))
    values.pop("plan_sha256", None)
    return _valid_sha256(digest) and digest == _canonical_sha256(values)


def _prior_attempt_has_no_target(payload: Mapping[str, Any]) -> bool:
    counts = payload.get("record_counts") or {}
    observed = payload.get("observed_time_range") or {}
    return (
        counts.get("measurements") == 0
        and observed.get("start") is None
        and observed.get("end") is None
    )


def _parse_http_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %Z")
    except ValueError:
        return None


def _require_aware_timestamp(value: Any) -> datetime:
    parsed = _parse_aware_timestamp(value)
    if parsed is None:
        raise ValueError("state_prior_p1_protocol_closure_created_at_invalid")
    return parsed


def _parse_aware_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _canonical_sha256(payload: Any) -> str:
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


def _unique_nonempty_strings(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
