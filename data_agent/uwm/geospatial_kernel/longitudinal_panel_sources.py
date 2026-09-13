"""Source admission for longitudinal causal panels used by the GWM kernel."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

from .spatiotemporal_causal_design import (
    LONGITUDINAL_DESIGN_GATES,
    LONGITUDINAL_ESTIMATION_GATES,
)


LONGITUDINAL_PANEL_SOURCE_SCHEMA = (
    "gwm.geospatial_kernel.longitudinal_panel_source_contract.v1"
)
LONGITUDINAL_PANEL_SOURCE_ROLES = (
    "treatment_events",
    "observed_outcomes",
    "time_varying_confounders",
    "spatial_units",
    "interference_network",
)
LONGITUDINAL_PANEL_CROSSWALK_GATES = (
    "treatment_to_unit",
    "outcome_to_unit",
    "confounder_to_unit",
    "unit_time_alignment",
    "network_to_unit_time",
    "no_future_information_leakage",
)

_PROBE_STATUSES = {"pass", "fail", "blocked", "not_run", "review"}
_ACCESS_BOUNDARIES = {
    "none",
    "api_key_optional",
    "api_key_required",
    "login_required",
    "restricted",
    "paywalled",
    "browser_or_waf",
    "interactive_selection_required",
    "external_candidate_required",
}


def build_longitudinal_panel_source_contract(
    *,
    candidate: Mapping[str, Any],
    sources: list[Mapping[str, Any]],
    crosswalk_evidence: Mapping[str, Any],
    probe_policy: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a role-separated, non-compensatory source admission contract."""

    normalized_sources = sorted(
        [deepcopy(dict(source)) for source in sources],
        key=lambda source: (str(source.get("role")), str(source.get("source_id"))),
    )
    normalized_crosswalks = _normalize_crosswalk_evidence(crosswalk_evidence)
    readiness = _source_readiness(normalized_sources, normalized_crosswalks)
    contract = {
        "schema": LONGITUDINAL_PANEL_SOURCE_SCHEMA,
        "candidate": deepcopy(dict(candidate)),
        "sources": normalized_sources,
        "crosswalk_evidence": normalized_crosswalks,
        "probe_policy": deepcopy(dict(probe_policy)),
        "provenance": deepcopy(dict(provenance)),
        "readiness": readiness,
        "admission": {
            "aggregation": "non_compensatory_all_roles_and_crosswalks",
            "metadata_admitted": readiness["all_source_metadata_ready"],
            "samples_admitted": readiness["all_source_samples_ready"],
            "panel_materialization_admitted": False,
            "causal_estimation_admitted": False,
            "effect_application_admitted": False,
        },
        "claim_boundary": {
            "source_discovery_not_dataset_validation": True,
            "catalog_record_not_observation": True,
            "policy_record_not_observed_outcome": True,
            "panel_materialization_not_causal_identification": True,
            "empirical_policy_effect_claim": False,
            "general_geospatial_kernel_validated": False,
            "gwm_k0_validated": False,
        },
    }
    contract["contract_digest"] = _canonical_digest(contract)
    return contract


def validate_longitudinal_panel_source_contract(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate source roles, probe evidence, readiness, and claim boundaries."""

    contract = dict(payload or {})
    errors: list[str] = []
    if contract.get("schema") != LONGITUDINAL_PANEL_SOURCE_SCHEMA:
        errors.append("schema_mismatch")

    candidate = contract.get("candidate")
    if not isinstance(candidate, Mapping):
        errors.append("candidate_required")
        candidate = {}
    for field in (
        "candidate_id",
        "domain_instance",
        "geography",
        "target_unit",
        "target_cadence",
        "treatment_definition",
        "outcome_definition",
    ):
        if not _is_explicit(candidate.get(field)):
            errors.append(f"candidate_{field}_required")

    sources = contract.get("sources")
    if not isinstance(sources, list):
        errors.append("sources_must_be_list")
        sources = []
    role_counts = {role: 0 for role in LONGITUDINAL_PANEL_SOURCE_ROLES}
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        prefix = f"sources_{index}"
        if not isinstance(source, Mapping):
            errors.append(f"{prefix}_must_be_object")
            continue
        role = source.get("role")
        if role not in role_counts:
            errors.append(f"{prefix}_role_invalid")
        else:
            role_counts[str(role)] += 1
        source_id = source.get("source_id")
        if not _is_explicit(source_id):
            errors.append(f"{prefix}_source_id_required")
        elif str(source_id) in source_ids:
            errors.append(f"duplicate_source_id:{source_id}")
        else:
            source_ids.add(str(source_id))
        for field in (
            "publisher",
            "canonical_url",
            "platform",
            "authority_status",
            "access_boundary",
            "metadata_probe_status",
            "schema_probe_status",
            "license_status",
            "time_coverage_status",
            "geography_coverage_status",
            "sample_validation_status",
            "temporal_semantics",
        ):
            if not _is_explicit(source.get(field)):
                errors.append(f"{prefix}_{field}_required")
        if source.get("access_boundary") not in _ACCESS_BOUNDARIES:
            errors.append(f"{prefix}_access_boundary_invalid")
        for field in (
            "metadata_probe_status",
            "schema_probe_status",
            "license_status",
            "time_coverage_status",
            "geography_coverage_status",
            "sample_validation_status",
        ):
            if source.get(field) not in _PROBE_STATUSES:
                errors.append(f"{prefix}_{field}_invalid")
        for field in (
            "stable_id_fields",
            "time_fields",
            "geometry_fields",
            "evidence_refs",
        ):
            if not _is_string_list(source.get(field), allow_empty=True):
                errors.append(f"{prefix}_{field}_must_be_string_list")
        if source.get("metadata_probe_status") == "pass" and not source.get(
            "evidence_refs"
        ):
            errors.append(f"{prefix}_metadata_pass_requires_evidence_refs")
        if source.get("sample_validation_status") == "pass" and not source.get(
            "stable_id_fields"
        ):
            errors.append(f"{prefix}_sample_pass_requires_stable_ids")
        if source.get("sample_validation_status") == "pass" and not source.get(
            "time_fields"
        ):
            errors.append(f"{prefix}_sample_pass_requires_time_fields")

    for role, count in role_counts.items():
        if count == 0:
            errors.append(f"source_role_missing:{role}")

    crosswalks = contract.get("crosswalk_evidence")
    if not isinstance(crosswalks, Mapping):
        errors.append("crosswalk_evidence_required")
        crosswalks = {}
    for gate_name in LONGITUDINAL_PANEL_CROSSWALK_GATES:
        gate = crosswalks.get(gate_name)
        if not isinstance(gate, Mapping):
            errors.append(f"crosswalk_evidence_{gate_name}_required")
            continue
        if not isinstance(gate.get("passed"), bool):
            errors.append(f"crosswalk_evidence_{gate_name}_passed_must_be_boolean")
        if not _is_string_list(gate.get("evidence_refs"), allow_empty=True):
            errors.append(f"crosswalk_evidence_{gate_name}_refs_must_be_string_list")
        elif gate.get("passed") is True and not gate.get("evidence_refs"):
            errors.append(f"crosswalk_evidence_{gate_name}_pass_requires_refs")

    probe_policy = contract.get("probe_policy")
    if not isinstance(probe_policy, Mapping):
        errors.append("probe_policy_required")
        probe_policy = {}
    for field in (
        "probe_only",
        "full_download_authorized",
        "bulk_download_performed",
        "training_panel_materialized",
    ):
        if not isinstance(probe_policy.get(field), bool):
            errors.append(f"probe_policy_{field}_must_be_boolean")
    if probe_policy.get("full_download_authorized") is not False:
        errors.append("probe_policy_full_download_authorized_must_be_false")
    bounded_bulk_authorized = probe_policy.get(
        "bounded_bulk_download_authorized", False
    )
    if not isinstance(bounded_bulk_authorized, bool):
        errors.append(
            "probe_policy_bounded_bulk_download_authorized_must_be_boolean"
        )
    if probe_policy.get("bulk_download_performed") is True:
        if probe_policy.get("probe_only") is not False:
            errors.append("probe_policy_bulk_download_requires_non_probe_mode")
        if bounded_bulk_authorized is not True:
            errors.append(
                "probe_policy_bulk_download_requires_bounded_authorization"
            )
    if probe_policy.get("training_panel_materialized") is not False:
        errors.append("probe_policy_training_panel_materialized_must_be_false")

    provenance = contract.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append("provenance_required")
        provenance = {}
    for field in (
        "top_level_skill",
        "route_type",
        "selected_skills",
        "probed_at",
    ):
        if not _is_explicit(provenance.get(field)):
            errors.append(f"provenance_{field}_required")
    if not _is_string_list(provenance.get("selected_skills")):
        errors.append("provenance_selected_skills_must_be_string_list")
    if provenance.get("top_level_skill") != "urban-data-seeker":
        errors.append("provenance_top_level_skill_mismatch")

    expected_readiness = _source_readiness(sources, crosswalks)
    if contract.get("readiness") != expected_readiness:
        errors.append("readiness_not_reproducible_from_sources")
    admission = contract.get("admission")
    if not isinstance(admission, Mapping):
        errors.append("admission_required")
    else:
        if admission.get("aggregation") != (
            "non_compensatory_all_roles_and_crosswalks"
        ):
            errors.append("admission_aggregation_must_be_non_compensatory")
        for field, readiness_field in (
            ("metadata_admitted", "all_source_metadata_ready"),
            ("samples_admitted", "all_source_samples_ready"),
        ):
            if admission.get(field) is not expected_readiness[readiness_field]:
                errors.append(f"admission_{field}_not_reproducible")
        if admission.get("panel_materialization_admitted") is not False:
            errors.append("panel_materialization_admitted_must_be_false")
        if admission.get("causal_estimation_admitted") is not False:
            errors.append("causal_estimation_admitted_must_be_false")
        if admission.get("effect_application_admitted") is not False:
            errors.append("effect_application_admitted_must_be_false")

    boundary = contract.get("claim_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("claim_boundary_required")
    else:
        for field in (
            "source_discovery_not_dataset_validation",
            "catalog_record_not_observation",
            "policy_record_not_observed_outcome",
            "panel_materialization_not_causal_identification",
        ):
            if boundary.get(field) is not True:
                errors.append(f"claim_boundary_{field}_must_be_true")
        for field in (
            "empirical_policy_effect_claim",
            "general_geospatial_kernel_validated",
            "gwm_k0_validated",
        ):
            if boundary.get(field) is not False:
                errors.append(f"claim_boundary_{field}_must_be_false")

    digest = contract.get("contract_digest")
    if not _is_sha256(digest):
        errors.append("contract_digest_invalid")
    elif digest != _canonical_digest(contract, excluded_keys={"contract_digest"}):
        errors.append("contract_digest_mismatch")

    return {
        "schema": "gwm.geospatial_kernel.longitudinal_panel_source_validation.v1",
        "valid": not errors,
        "errors": errors,
        **expected_readiness,
        "causal_estimation_admitted": False,
        "effect_application_admitted": False,
        "general_geospatial_kernel_validated": False,
        "gwm_k0_validated": False,
    }


def seed_spatiotemporal_gate_evidence_from_panel_sources(
    source_contract: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Seed closed design gates from a validated source acquisition contract."""

    validation = validate_longitudinal_panel_source_contract(source_contract)
    if not validation["valid"]:
        raise ValueError(
            "longitudinal_panel_source_contract_invalid:"
            + str(validation["errors"][0])
        )
    evidence_ref = "panel_source_contract:" + str(source_contract["contract_digest"])
    reason = (
        "source_panel_not_materialization_ready"
        if not validation["panel_materialization_ready"]
        else "source_panel_ready_but_materialization_and_design_checks_not_run"
    )
    return {
        gate_name: {
            "passed": False,
            "evidence_refs": [evidence_ref],
            "details": {
                "reason": reason,
                "panel_materialization_ready": validation[
                    "panel_materialization_ready"
                ],
            },
        }
        for gate_name in (*LONGITUDINAL_DESIGN_GATES, *LONGITUDINAL_ESTIMATION_GATES)
    }


def _normalize_crosswalk_evidence(
    crosswalk_evidence: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    normalized = {}
    for gate_name in LONGITUDINAL_PANEL_CROSSWALK_GATES:
        raw = crosswalk_evidence.get(gate_name)
        raw = dict(raw) if isinstance(raw, Mapping) else {}
        refs = raw.get("evidence_refs")
        refs = refs if isinstance(refs, list) else []
        normalized[gate_name] = {
            "passed": raw.get("passed") is True,
            "evidence_refs": sorted(
                {str(value) for value in refs if str(value).strip()}
            ),
            "details": deepcopy(dict(raw.get("details") or {}))
            if isinstance(raw.get("details"), Mapping)
            else {},
        }
    return normalized


def _source_readiness(
    sources: list[Any], crosswalks: Mapping[str, Any]
) -> dict[str, Any]:
    indexed: dict[str, list[Mapping[str, Any]]] = {
        role: [] for role in LONGITUDINAL_PANEL_SOURCE_ROLES
    }
    for source in sources:
        if (
            isinstance(source, Mapping)
            and source.get("role") in LONGITUDINAL_PANEL_SOURCE_ROLES
        ):
            indexed[str(source["role"])].append(source)
    metadata_blockers = []
    sample_blockers = []
    role_readiness: dict[str, Any] = {}
    for role in LONGITUDINAL_PANEL_SOURCE_ROLES:
        role_sources = indexed[role]
        metadata_ready = bool(
            role_sources and all(_metadata_ready(source) for source in role_sources)
        )
        sample_ready = bool(
            metadata_ready
            and all(
                source.get("sample_validation_status") == "pass"
                for source in role_sources
            )
        )
        role_readiness[role] = {
            "source_ids": [source.get("source_id") for source in role_sources],
            "metadata_ready": metadata_ready,
            "sample_ready": sample_ready,
        }
        if not metadata_ready:
            metadata_blockers.append(role)
        if not sample_ready:
            sample_blockers.append(role)
    blocking_crosswalks = [
        gate_name
        for gate_name in LONGITUDINAL_PANEL_CROSSWALK_GATES
        if not _evidence_gate_passed(crosswalks.get(gate_name))
    ]
    metadata_ready = not metadata_blockers
    samples_ready = not sample_blockers
    crosswalk_ready = not blocking_crosswalks
    panel_materialization_ready = metadata_ready and samples_ready and crosswalk_ready
    return {
        "role_readiness": role_readiness,
        "all_source_metadata_ready": metadata_ready,
        "all_source_samples_ready": samples_ready,
        "all_crosswalks_ready": crosswalk_ready,
        "panel_materialization_ready": panel_materialization_ready,
        "panel_materialization_admitted": False,
        "blocking_metadata_roles": metadata_blockers,
        "blocking_sample_roles": sample_blockers,
        "blocking_crosswalks": blocking_crosswalks,
    }


def _metadata_ready(source: Mapping[str, Any]) -> bool:
    return bool(
        source.get("authority_status") == "verified_official"
        and all(
            source.get(field) == "pass"
            for field in (
                "metadata_probe_status",
                "schema_probe_status",
                "license_status",
                "time_coverage_status",
                "geography_coverage_status",
            )
        )
    )


def _evidence_gate_passed(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("passed") is True
        and _is_string_list(value.get("evidence_refs"))
    )


def _is_explicit(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _is_string_list(value: Any, *, allow_empty: bool = False) -> bool:
    return bool(
        isinstance(value, list)
        and (allow_empty or value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_digest(
    payload: Mapping[str, Any], *, excluded_keys: set[str] | None = None
) -> str:
    excluded = excluded_keys or set()
    content = {key: value for key, value in payload.items() if key not in excluded}
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
