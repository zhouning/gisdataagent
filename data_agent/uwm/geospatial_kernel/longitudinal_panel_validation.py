"""Row-level longitudinal panel validation for the shared GWM kernel."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from typing import Any, Mapping, Sequence

from .longitudinal_panel_sources import (
    LONGITUDINAL_PANEL_SOURCE_ROLES,
    validate_longitudinal_panel_source_contract,
)
from .spatiotemporal_causal_design import (
    LONGITUDINAL_DESIGN_GATES,
    LONGITUDINAL_ESTIMATION_GATES,
)


LONGITUDINAL_PANEL_VALIDATION_SCHEMA = (
    "gwm.geospatial_kernel.longitudinal_panel_validation.v1"
)
LONGITUDINAL_PANEL_VALIDATION_CHECKS = (
    "required_columns_present",
    "unit_time_index_unique",
    "stable_unit_and_source_ids",
    "treatment_outcome_role_separated",
    "temporal_order_verified",
    "treatment_precedes_outcome",
    "pre_post_coverage_verified",
    "time_varying_confounders_measured",
    "observed_outcomes_present",
    "missingness_and_censoring_declared",
    "treatment_to_unit_crosswalk_integrity",
    "network_crosswalk_integrity",
    "interference_mapping_versioned",
    "network_vintage_alignment_verified",
    "no_future_information_leakage",
    "source_hash_coverage_complete",
)

_EVIDENCE_CLASSES = {"synthetic_fixture", "materialized_empirical_panel"}
_MATERIALIZATION_STATUSES = {"synthetic_only", "materialized"}
_NETWORK_TIME_MODES = {"fixed_at_baseline", "lagged_dynamic"}


def build_longitudinal_panel_validation_contract(
    *,
    source_contract: Mapping[str, Any],
    panel_rows: Sequence[Mapping[str, Any]],
    network_rows: Sequence[Mapping[str, Any]],
    field_mapping: Mapping[str, Any],
    network_field_mapping: Mapping[str, Any],
    temporal_policy: Mapping[str, Any],
    missingness_policy: Mapping[str, Any],
    materialization: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Audit materialized rows without treating validation as identification."""

    normalized_panel = _normalize_rows(panel_rows)
    normalized_network = _normalize_rows(network_rows)
    source = deepcopy(dict(source_contract))
    mapping = deepcopy(dict(field_mapping))
    network_mapping = deepcopy(dict(network_field_mapping))
    temporal = deepcopy(dict(temporal_policy))
    missingness = deepcopy(dict(missingness_policy))
    materialization_section = deepcopy(dict(materialization))
    provenance_section = deepcopy(dict(provenance))
    row_hashes = {
        "panel_rows_sha256": _canonical_digest(normalized_panel),
        "network_rows_sha256": _canonical_digest(normalized_network),
    }
    audit = _audit_rows(
        source_contract=source,
        panel_rows=normalized_panel,
        network_rows=normalized_network,
        field_mapping=mapping,
        network_field_mapping=network_mapping,
        temporal_policy=temporal,
        missingness_policy=missingness,
        provenance=provenance_section,
        row_hashes=row_hashes,
    )
    readiness = _assess_readiness(
        source_contract=source,
        audit=audit,
        materialization=materialization_section,
    )
    contract = {
        "schema": LONGITUDINAL_PANEL_VALIDATION_SCHEMA,
        "source_contract": source,
        "source_contract_digest": source.get("contract_digest"),
        "field_mapping": mapping,
        "network_field_mapping": network_mapping,
        "temporal_policy": temporal,
        "missingness_policy": missingness,
        "materialization": materialization_section,
        "provenance": provenance_section,
        "row_manifest": {
            "panel_row_count": len(normalized_panel),
            "network_row_count": len(normalized_network),
            **row_hashes,
        },
        "audit": audit,
        "readiness": readiness,
        "admission": {
            "aggregation": "non_compensatory_source_materialization_and_row_checks",
            "row_audit_admitted": readiness["row_validation_ready"],
            "empirical_panel_evidence_admitted": readiness[
                "empirical_panel_evidence_ready"
            ],
            "causal_estimation_admitted": False,
            "effect_application_admitted": False,
        },
        "claim_boundary": {
            "synthetic_validation_not_empirical_evidence": True,
            "panel_validation_not_causal_identification": True,
            "observed_panel_not_exchangeability_proof": True,
            "identified_policy_effect": False,
            "empirical_policy_effect_claim": False,
            "general_geospatial_kernel_validated": False,
            "gwm_k0_validated": False,
        },
    }
    contract["contract_digest"] = _canonical_digest(contract)
    return contract


def validate_longitudinal_panel_validation_contract(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate row-audit structure, nested source evidence, and admission."""

    contract = dict(payload or {})
    errors: list[str] = []
    if contract.get("schema") != LONGITUDINAL_PANEL_VALIDATION_SCHEMA:
        errors.append("schema_mismatch")

    source_contract = contract.get("source_contract")
    if not isinstance(source_contract, Mapping):
        errors.append("source_contract_required")
        source_contract = {}
    source_validation = validate_longitudinal_panel_source_contract(source_contract)
    if not source_validation["valid"]:
        errors.append("source_contract_invalid")
    if contract.get("source_contract_digest") != source_contract.get(
        "contract_digest"
    ):
        errors.append("source_contract_digest_mismatch")

    field_mapping = _require_mapping(contract, "field_mapping", errors)
    _validate_field_mapping(field_mapping, errors)
    network_mapping = _require_mapping(
        contract, "network_field_mapping", errors
    )
    _validate_network_field_mapping(network_mapping, errors)
    temporal_policy = _require_mapping(contract, "temporal_policy", errors)
    _validate_temporal_policy(temporal_policy, errors)
    missingness_policy = _require_mapping(
        contract, "missingness_policy", errors
    )
    _validate_missingness_policy(missingness_policy, field_mapping, errors)
    materialization = _require_mapping(contract, "materialization", errors)
    _validate_materialization(materialization, errors)
    provenance = _require_mapping(contract, "provenance", errors)
    _validate_provenance(provenance, errors)

    manifest = _require_mapping(contract, "row_manifest", errors)
    for field in ("panel_row_count", "network_row_count"):
        value = manifest.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"row_manifest_{field}_invalid")
    for field in ("panel_rows_sha256", "network_rows_sha256"):
        if not _is_sha256(manifest.get(field)):
            errors.append(f"row_manifest_{field}_invalid")

    audit = contract.get("audit")
    if not isinstance(audit, Mapping):
        errors.append("audit_required")
        audit = {}
    for check_name in LONGITUDINAL_PANEL_VALIDATION_CHECKS:
        check = audit.get(check_name)
        if not isinstance(check, Mapping):
            errors.append(f"audit_{check_name}_required")
            continue
        if not isinstance(check.get("passed"), bool):
            errors.append(f"audit_{check_name}_passed_must_be_boolean")
        refs = check.get("evidence_refs")
        if not _is_string_list(refs, allow_empty=True):
            errors.append(f"audit_{check_name}_refs_must_be_string_list")
        elif check.get("passed") is True and not refs:
            errors.append(f"audit_{check_name}_pass_requires_refs")
        if not isinstance(check.get("details"), Mapping):
            errors.append(f"audit_{check_name}_details_must_be_object")

    allowed_evidence_refs = {
        "panel_rows_sha256:" + str(manifest.get("panel_rows_sha256")),
        "network_rows_sha256:" + str(manifest.get("network_rows_sha256")),
        "panel_source_contract:" + str(contract.get("source_contract_digest")),
    }
    for check_name in LONGITUDINAL_PANEL_VALIDATION_CHECKS:
        check = audit.get(check_name)
        if not isinstance(check, Mapping):
            continue
        refs = check.get("evidence_refs")
        if isinstance(refs, list) and any(
            ref not in allowed_evidence_refs for ref in refs
        ):
            errors.append(f"audit_{check_name}_evidence_ref_not_bound_to_manifest")
    unit_time_check = audit.get("unit_time_index_unique")
    if isinstance(unit_time_check, Mapping):
        details = unit_time_check.get("details")
        if isinstance(details, Mapping) and details.get("row_count") != manifest.get(
            "panel_row_count"
        ):
            errors.append("audit_unit_time_row_count_mismatch")

    expected_readiness = _assess_readiness(
        source_contract=source_contract,
        audit=audit,
        materialization=materialization,
    )
    if contract.get("readiness") != expected_readiness:
        errors.append("readiness_not_reproducible_from_contract")

    admission = contract.get("admission")
    if not isinstance(admission, Mapping):
        errors.append("admission_required")
    else:
        if admission.get("aggregation") != (
            "non_compensatory_source_materialization_and_row_checks"
        ):
            errors.append("admission_aggregation_invalid")
        if admission.get("row_audit_admitted") is not expected_readiness[
            "row_validation_ready"
        ]:
            errors.append("admission_row_audit_not_reproducible")
        if admission.get(
            "empirical_panel_evidence_admitted"
        ) is not expected_readiness["empirical_panel_evidence_ready"]:
            errors.append("admission_empirical_panel_not_reproducible")
        for field in ("causal_estimation_admitted", "effect_application_admitted"):
            if admission.get(field) is not False:
                errors.append(f"admission_{field}_must_be_false")

    boundary = contract.get("claim_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("claim_boundary_required")
    else:
        for field in (
            "synthetic_validation_not_empirical_evidence",
            "panel_validation_not_causal_identification",
            "observed_panel_not_exchangeability_proof",
        ):
            if boundary.get(field) is not True:
                errors.append(f"claim_boundary_{field}_must_be_true")
        for field in (
            "identified_policy_effect",
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
        "schema": "gwm.geospatial_kernel.longitudinal_panel_validation_result.v1",
        "valid": not errors,
        "errors": errors,
        **expected_readiness,
        "causal_estimation_admitted": False,
        "effect_application_admitted": False,
        "general_geospatial_kernel_validated": False,
        "gwm_k0_validated": False,
    }


def seed_spatiotemporal_gate_evidence_from_panel_validation(
    panel_validation_contract: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Derive only gates directly demonstrated by an admitted empirical panel."""

    validation = validate_longitudinal_panel_validation_contract(
        panel_validation_contract
    )
    if not validation["valid"]:
        raise ValueError(
            "longitudinal_panel_validation_contract_invalid:"
            + str(validation["errors"][0])
        )
    empirical_ready = validation["empirical_panel_evidence_ready"]
    audit = panel_validation_contract["audit"]
    digest = str(panel_validation_contract["contract_digest"])
    gate_checks: dict[str, tuple[str, ...]] = {
        "unit_time_index_unique": ("unit_time_index_unique",),
        "temporal_order_verified": ("temporal_order_verified",),
        "treatment_precedes_outcome": ("treatment_precedes_outcome",),
        "pre_treatment_covariates_verified": (
            "temporal_order_verified",
            "time_varying_confounders_measured",
        ),
        "time_varying_confounders_measured": (
            "time_varying_confounders_measured",
        ),
        "interference_exposure_mapping_versioned": (
            "interference_mapping_versioned",
        ),
        "network_time_alignment_verified": (
            "network_vintage_alignment_verified",
        ),
        "no_future_information_leakage": (
            "no_future_information_leakage",
        ),
        "observed_policy_outcome_available": ("observed_outcomes_present",),
    }
    evidence: dict[str, dict[str, Any]] = {}
    for gate_name in (*LONGITUDINAL_DESIGN_GATES, *LONGITUDINAL_ESTIMATION_GATES):
        checks = gate_checks.get(gate_name, ())
        passed = bool(
            empirical_ready
            and checks
            and all(audit[name]["passed"] is True for name in checks)
        )
        if not empirical_ready:
            reason = "empirical_panel_evidence_not_ready"
        elif not checks:
            reason = "requires_separate_design_or_estimation_diagnostic"
        elif not passed:
            reason = "required_panel_check_failed"
        else:
            reason = "hash_bound_empirical_panel_checks_passed"
        evidence[gate_name] = {
            "passed": passed,
            "evidence_refs": [
                f"longitudinal_panel_validation:{digest}#{name}" for name in checks
            ]
            if passed
            else [],
            "details": {
                "reason": reason,
                "required_panel_checks": list(checks),
                "empirical_panel_evidence_ready": empirical_ready,
                "panel_validation_contract_digest": digest,
            },
        }
    return evidence


def _audit_rows(
    *,
    source_contract: Mapping[str, Any],
    panel_rows: list[dict[str, Any]],
    network_rows: list[dict[str, Any]],
    field_mapping: Mapping[str, Any],
    network_field_mapping: Mapping[str, Any],
    temporal_policy: Mapping[str, Any],
    missingness_policy: Mapping[str, Any],
    provenance: Mapping[str, Any],
    row_hashes: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    panel_ref = "panel_rows_sha256:" + row_hashes["panel_rows_sha256"]
    network_ref = "network_rows_sha256:" + row_hashes["network_rows_sha256"]
    source_ref = "panel_source_contract:" + str(
        source_contract.get("contract_digest", "missing")
    )

    panel_fields = _panel_required_fields(field_mapping)
    network_fields = _network_required_fields(network_field_mapping)
    missing_panel_columns = _missing_columns(panel_rows, panel_fields)
    missing_network_columns = _missing_columns(network_rows, network_fields)
    required_columns_passed = bool(
        panel_rows
        and network_rows
        and not missing_panel_columns
        and not missing_network_columns
    )

    unit_field = field_mapping.get("unit_id_field")
    time_field = field_mapping.get("panel_time_field")
    panel_keys = [
        (row.get(unit_field), row.get(time_field))
        for row in panel_rows
        if isinstance(unit_field, str) and isinstance(time_field, str)
    ]
    unit_time_unique = bool(
        required_columns_passed
        and len(panel_keys) == len(set(_hashable_key(key) for key in panel_keys))
    )

    source_ids_by_role = _source_ids_by_role(source_contract)
    source_id_fields = field_mapping.get("source_id_fields")
    source_id_fields = source_id_fields if isinstance(source_id_fields, Mapping) else {}
    stable_ids = required_columns_passed and all(
        _is_explicit(row.get(unit_field)) for row in panel_rows
    )
    for role in LONGITUDINAL_PANEL_SOURCE_ROLES[:-1]:
        field = source_id_fields.get(role)
        allowed = source_ids_by_role.get(role, set())
        stable_ids = bool(
            stable_ids
            and isinstance(field, str)
            and allowed
            and all(row.get(field) in allowed for row in panel_rows)
        )
    network_source_field = network_field_mapping.get("source_id_field")
    stable_ids = bool(
        stable_ids
        and source_ids_by_role.get("interference_network")
        and all(
            row.get(network_source_field)
            in source_ids_by_role["interference_network"]
            for row in network_rows
        )
    )

    treatment_field = field_mapping.get("treatment_field")
    outcome_field = field_mapping.get("outcome_field")
    treatment_source_field = source_id_fields.get("treatment_events")
    outcome_source_field = source_id_fields.get("observed_outcomes")
    role_separated = bool(
        required_columns_passed
        and treatment_field != outcome_field
        and treatment_source_field != outcome_source_field
        and source_ids_by_role.get("treatment_events", set()).isdisjoint(
            source_ids_by_role.get("observed_outcomes", set())
        )
    )

    parsed_panel = _parse_panel_times(panel_rows, field_mapping)
    all_times_valid = len(parsed_panel) == len(panel_rows)
    temporal_order = bool(
        required_columns_passed
        and all_times_valid
        and all(
            item["confounder_time"] <= item["treatment_time"]
            and item["panel_time"] <= item["treatment_time"]
            and item["treatment_time"] < item["outcome_time"]
            for item in parsed_panel
        )
    )
    treatment_precedes_outcome = bool(
        required_columns_passed
        and all_times_valid
        and all(
            item["treatment_time"] < item["outcome_time"]
            for item in parsed_panel
        )
    )

    index_time = _parse_timestamp(temporal_policy.get("index_treatment_time"))
    minimum_pre = temporal_policy.get("minimum_pre_periods")
    minimum_post = temporal_policy.get("minimum_post_periods")
    units = {
        row.get(unit_field)
        for row in panel_rows
        if isinstance(unit_field, str) and _is_explicit(row.get(unit_field))
    }
    coverage_by_unit: dict[str, dict[str, int]] = {}
    coverage_passed = bool(units and index_time is not None)
    for unit in sorted(units, key=str):
        times = {
            item["panel_time"]
            for item in parsed_panel
            if item["unit_id"] == unit
        }
        pre_count = sum(value < index_time for value in times) if index_time else 0
        post_count = sum(value >= index_time for value in times) if index_time else 0
        coverage_by_unit[str(unit)] = {"pre": pre_count, "post": post_count}
        coverage_passed = bool(
            coverage_passed
            and isinstance(minimum_pre, int)
            and not isinstance(minimum_pre, bool)
            and isinstance(minimum_post, int)
            and not isinstance(minimum_post, bool)
            and pre_count >= minimum_pre
            and post_count >= minimum_post
        )

    confounder_fields = field_mapping.get("time_varying_confounder_fields")
    confounder_fields = confounder_fields if isinstance(confounder_fields, list) else []
    confounders_measured = bool(
        required_columns_passed
        and confounder_fields
        and all(
            all(row.get(field) is not None for field in confounder_fields)
            for row in panel_rows
        )
    )
    observed_outcomes = bool(
        required_columns_passed
        and any(row.get(outcome_field) is not None for row in panel_rows)
    )

    censoring_field = missingness_policy.get("censoring_indicator_field")
    censored_value = missingness_policy.get("censoring_value_when_missing")
    allowed_missing = missingness_policy.get("allowed_missing_fields")
    allowed_missing = (
        set(allowed_missing) if isinstance(allowed_missing, list) else set()
    )
    missingness_declared = bool(
        missingness_policy.get("declared") is True
        and _is_explicit(missingness_policy.get("strategy"))
        and censoring_field == field_mapping.get("censoring_indicator_field")
        and isinstance(allowed_missing, set)
        and all(
            row.get(outcome_field) is not None
            or (
                outcome_field in allowed_missing
                and row.get(censoring_field) == censored_value
            )
            for row in panel_rows
        )
    )

    treated_rows = [
        row
        for row in panel_rows
        if row.get(treatment_field) not in (None, 0, False)
    ]
    treatment_crosswalk = bool(
        stable_ids
        and treated_rows
        and all(
            row.get(treatment_source_field)
            in source_ids_by_role.get("treatment_events", set())
            and _is_explicit(row.get(unit_field))
            for row in treated_rows
        )
    )

    from_field = network_field_mapping.get("from_unit_id_field")
    to_field = network_field_mapping.get("to_unit_id_field")
    version_field = network_field_mapping.get("mapping_version_field")
    valid_from_field = network_field_mapping.get("valid_from_field")
    valid_to_field = network_field_mapping.get("valid_to_field")
    panel_version_field = field_mapping.get("network_mapping_version_field")
    network_times = _parse_network_times(network_rows, network_field_mapping)
    network_crosswalk = bool(
        required_columns_passed
        and len(network_times) == len(network_rows)
        and all(
            row.get(from_field) in units
            and row.get(to_field) in units
            and row.get(from_field) != row.get(to_field)
            for row in network_rows
        )
    )
    mapping_versioned = bool(
        network_crosswalk
        and all(_is_explicit(row.get(version_field)) for row in network_rows)
        and all(_is_explicit(row.get(panel_version_field)) for row in panel_rows)
    )
    network_alignment = bool(network_crosswalk and mapping_versioned)
    for item in parsed_panel:
        active = [
            network
            for network in network_times
            if item["unit_id"] in (network["from_unit_id"], network["to_unit_id"])
            and network["valid_from"] <= item["treatment_time"]
            < network["valid_to"]
            and network["mapping_version"] == item["network_mapping_version"]
        ]
        if not active:
            network_alignment = False
            break

    feature_available_field = field_mapping.get("feature_available_at_field")
    no_future_leakage = bool(
        temporal_order
        and network_alignment
        and all(
            item["feature_available_at"] <= item["treatment_time"]
            for item in parsed_panel
        )
        and all(
            _parse_timestamp(row.get(valid_from_field)) is not None
            and _parse_timestamp(row.get(valid_to_field)) is not None
            for row in network_rows
        )
        and isinstance(feature_available_field, str)
    )

    artifact_hashes = provenance.get("source_artifact_hashes")
    artifact_hashes = artifact_hashes if isinstance(artifact_hashes, Mapping) else {}
    required_source_ids = set().union(*source_ids_by_role.values())
    source_hash_coverage = bool(
        required_source_ids
        and set(artifact_hashes) == required_source_ids
        and all(_is_sha256(value) for value in artifact_hashes.values())
    )

    return {
        "required_columns_present": _check(
            required_columns_passed,
            [panel_ref, network_ref],
            {
                "missing_panel_columns": missing_panel_columns,
                "missing_network_columns": missing_network_columns,
            },
        ),
        "unit_time_index_unique": _check(
            unit_time_unique,
            [panel_ref],
            {
                "row_count": len(panel_rows),
                "unique_key_count": len(
                    set(_hashable_key(key) for key in panel_keys)
                ),
            },
        ),
        "stable_unit_and_source_ids": _check(
            stable_ids, [panel_ref, network_ref, source_ref], {}
        ),
        "treatment_outcome_role_separated": _check(
            role_separated, [panel_ref, source_ref], {}
        ),
        "temporal_order_verified": _check(
            temporal_order,
            [panel_ref],
            {"required_order": "panel_time<=L_t<=A_t<Y_t_plus_1"},
        ),
        "treatment_precedes_outcome": _check(
            treatment_precedes_outcome, [panel_ref], {}
        ),
        "pre_post_coverage_verified": _check(
            coverage_passed,
            [panel_ref],
            {"coverage_by_unit": coverage_by_unit},
        ),
        "time_varying_confounders_measured": _check(
            confounders_measured,
            [panel_ref],
            {"fields": confounder_fields},
        ),
        "observed_outcomes_present": _check(
            observed_outcomes, [panel_ref], {"outcome_field": outcome_field}
        ),
        "missingness_and_censoring_declared": _check(
            missingness_declared,
            [panel_ref],
            {"censoring_indicator_field": censoring_field},
        ),
        "treatment_to_unit_crosswalk_integrity": _check(
            treatment_crosswalk, [panel_ref, source_ref], {}
        ),
        "network_crosswalk_integrity": _check(
            network_crosswalk, [network_ref, source_ref], {}
        ),
        "interference_mapping_versioned": _check(
            mapping_versioned,
            [panel_ref, network_ref],
            {"network_time_mode": temporal_policy.get("network_time_mode")},
        ),
        "network_vintage_alignment_verified": _check(
            network_alignment, [panel_ref, network_ref], {}
        ),
        "no_future_information_leakage": _check(
            no_future_leakage, [panel_ref, network_ref], {}
        ),
        "source_hash_coverage_complete": _check(
            source_hash_coverage,
            [source_ref],
            {
                "required_source_ids": sorted(required_source_ids, key=str),
                "hashed_source_ids": sorted(artifact_hashes, key=str),
            },
        ),
    }


def _assess_readiness(
    *,
    source_contract: Mapping[str, Any],
    audit: Mapping[str, Any],
    materialization: Mapping[str, Any],
) -> dict[str, Any]:
    source_validation = validate_longitudinal_panel_source_contract(source_contract)
    blocking_checks = [
        name
        for name in LONGITUDINAL_PANEL_VALIDATION_CHECKS
        if not _check_passed(audit.get(name))
    ]
    row_ready = not blocking_checks
    source_ready = bool(
        source_validation["valid"]
        and source_validation["panel_materialization_ready"]
    )
    materialized_empirical = bool(
        materialization.get("evidence_class") == "materialized_empirical_panel"
        and materialization.get("status") == "materialized"
        and _is_explicit(materialization.get("authorization_ref"))
        and _is_explicit(materialization.get("materialized_at"))
        and _parse_timestamp(materialization.get("materialized_at")) is not None
        and _is_explicit(materialization.get("storage_ref"))
    )
    empirical_ready = source_ready and row_ready and materialized_empirical
    return {
        "source_panel_materialization_ready": source_ready,
        "row_validation_ready": row_ready,
        "materialized_empirical_panel_declared": materialized_empirical,
        "empirical_panel_evidence_ready": empirical_ready,
        "blocking_checks": blocking_checks,
        "causal_identification_ready": False,
        "effect_application_admitted": False,
    }


def _validate_field_mapping(mapping: Mapping[str, Any], errors: list[str]) -> None:
    scalar_fields = (
        "unit_id_field",
        "panel_time_field",
        "treatment_field",
        "treatment_time_field",
        "outcome_field",
        "outcome_time_field",
        "confounder_time_field",
        "feature_available_at_field",
        "censoring_indicator_field",
        "network_mapping_version_field",
    )
    for field in scalar_fields:
        if not _is_nonempty_string(mapping.get(field)):
            errors.append(f"field_mapping_{field}_required")
    for field in ("baseline_confounder_fields", "time_varying_confounder_fields"):
        if not _is_string_list(mapping.get(field)):
            errors.append(f"field_mapping_{field}_must_be_string_list")
    source_fields = mapping.get("source_id_fields")
    if not isinstance(source_fields, Mapping):
        errors.append("field_mapping_source_id_fields_must_be_object")
    else:
        for role in LONGITUDINAL_PANEL_SOURCE_ROLES[:-1]:
            if not _is_nonempty_string(source_fields.get(role)):
                errors.append(f"field_mapping_source_id_field_required:{role}")
    if mapping.get("treatment_field") == mapping.get("outcome_field"):
        errors.append("field_mapping_treatment_and_outcome_must_differ")


def _validate_network_field_mapping(
    mapping: Mapping[str, Any], errors: list[str]
) -> None:
    for field in (
        "from_unit_id_field",
        "to_unit_id_field",
        "valid_from_field",
        "valid_to_field",
        "source_id_field",
        "mapping_version_field",
    ):
        if not _is_nonempty_string(mapping.get(field)):
            errors.append(f"network_field_mapping_{field}_required")
    if mapping.get("from_unit_id_field") == mapping.get("to_unit_id_field"):
        errors.append("network_field_mapping_endpoints_must_differ")


def _validate_temporal_policy(policy: Mapping[str, Any], errors: list[str]) -> None:
    if _parse_timestamp(policy.get("index_treatment_time")) is None:
        errors.append("temporal_policy_index_treatment_time_invalid")
    for field in ("minimum_pre_periods", "minimum_post_periods"):
        value = policy.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            errors.append(f"temporal_policy_{field}_invalid")
    if policy.get("network_time_mode") not in _NETWORK_TIME_MODES:
        errors.append("temporal_policy_network_time_mode_invalid")


def _validate_missingness_policy(
    policy: Mapping[str, Any],
    field_mapping: Mapping[str, Any],
    errors: list[str],
) -> None:
    if not isinstance(policy.get("declared"), bool):
        errors.append("missingness_policy_declared_must_be_boolean")
    if not _is_explicit(policy.get("strategy")):
        errors.append("missingness_policy_strategy_required")
    if policy.get("censoring_indicator_field") != field_mapping.get(
        "censoring_indicator_field"
    ):
        errors.append("missingness_policy_censoring_field_mismatch")
    if not _is_string_list(policy.get("allowed_missing_fields"), allow_empty=True):
        errors.append("missingness_policy_allowed_missing_fields_must_be_string_list")
    if "censoring_value_when_missing" not in policy:
        errors.append("missingness_policy_censoring_value_required")


def _validate_materialization(
    materialization: Mapping[str, Any], errors: list[str]
) -> None:
    evidence_class = materialization.get("evidence_class")
    status = materialization.get("status")
    if evidence_class not in _EVIDENCE_CLASSES:
        errors.append("materialization_evidence_class_invalid")
    if status not in _MATERIALIZATION_STATUSES:
        errors.append("materialization_status_invalid")
    if evidence_class == "synthetic_fixture" and status != "synthetic_only":
        errors.append("synthetic_fixture_status_must_be_synthetic_only")
    if evidence_class == "materialized_empirical_panel":
        if status != "materialized":
            errors.append("empirical_panel_status_must_be_materialized")
        for field in (
            "authorization_ref",
            "materialized_at",
            "storage_ref",
        ):
            if not _is_explicit(materialization.get(field)):
                errors.append(f"materialization_{field}_required")
        if _parse_timestamp(materialization.get("materialized_at")) is None:
            errors.append("materialization_materialized_at_invalid")


def _validate_provenance(provenance: Mapping[str, Any], errors: list[str]) -> None:
    for field in ("validator_version", "generated_at"):
        if not _is_explicit(provenance.get(field)):
            errors.append(f"provenance_{field}_required")
    if _parse_timestamp(provenance.get("generated_at")) is None:
        errors.append("provenance_generated_at_invalid")
    hashes = provenance.get("source_artifact_hashes")
    if not isinstance(hashes, Mapping) or not hashes:
        errors.append("provenance_source_artifact_hashes_required")
    elif any(
        not _is_nonempty_string(name) or not _is_sha256(value)
        for name, value in hashes.items()
    ):
        errors.append("provenance_source_artifact_hash_invalid")


def _panel_required_fields(mapping: Mapping[str, Any]) -> set[str]:
    fields = {
        mapping.get("unit_id_field"),
        mapping.get("panel_time_field"),
        mapping.get("treatment_field"),
        mapping.get("treatment_time_field"),
        mapping.get("outcome_field"),
        mapping.get("outcome_time_field"),
        mapping.get("confounder_time_field"),
        mapping.get("feature_available_at_field"),
        mapping.get("censoring_indicator_field"),
        mapping.get("network_mapping_version_field"),
    }
    for key in ("baseline_confounder_fields", "time_varying_confounder_fields"):
        values = mapping.get(key)
        if isinstance(values, list):
            fields.update(values)
    source_fields = mapping.get("source_id_fields")
    if isinstance(source_fields, Mapping):
        fields.update(source_fields.values())
    return {str(field) for field in fields if _is_explicit(field)}


def _network_required_fields(mapping: Mapping[str, Any]) -> set[str]:
    return {
        str(mapping[field])
        for field in (
            "from_unit_id_field",
            "to_unit_id_field",
            "valid_from_field",
            "valid_to_field",
            "source_id_field",
            "mapping_version_field",
        )
        if _is_explicit(mapping.get(field))
    }


def _missing_columns(rows: list[dict[str, Any]], required: set[str]) -> list[str]:
    if not rows:
        return sorted(required)
    present_in_every_row = set.intersection(*(set(row) for row in rows))
    return sorted(required - present_in_every_row)


def _parse_panel_times(
    rows: list[dict[str, Any]], mapping: Mapping[str, Any]
) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    fields = {
        "panel_time": mapping.get("panel_time_field"),
        "treatment_time": mapping.get("treatment_time_field"),
        "outcome_time": mapping.get("outcome_time_field"),
        "confounder_time": mapping.get("confounder_time_field"),
        "feature_available_at": mapping.get("feature_available_at_field"),
    }
    for row in rows:
        times = {
            name: _parse_timestamp(row.get(field))
            for name, field in fields.items()
        }
        if any(value is None for value in times.values()):
            continue
        parsed.append(
            {
                **times,
                "unit_id": row.get(mapping.get("unit_id_field")),
                "network_mapping_version": row.get(
                    mapping.get("network_mapping_version_field")
                ),
            }
        )
    return parsed


def _parse_network_times(
    rows: list[dict[str, Any]], mapping: Mapping[str, Any]
) -> list[dict[str, Any]]:
    parsed = []
    for row in rows:
        valid_from = _parse_timestamp(row.get(mapping.get("valid_from_field")))
        valid_to = _parse_timestamp(row.get(mapping.get("valid_to_field")))
        if valid_from is None or valid_to is None or valid_from >= valid_to:
            continue
        parsed.append(
            {
                "from_unit_id": row.get(mapping.get("from_unit_id_field")),
                "to_unit_id": row.get(mapping.get("to_unit_id_field")),
                "valid_from": valid_from,
                "valid_to": valid_to,
                "mapping_version": row.get(mapping.get("mapping_version_field")),
            }
        )
    return parsed


def _source_ids_by_role(
    source_contract: Mapping[str, Any],
) -> dict[str, set[Any]]:
    result = {role: set() for role in LONGITUDINAL_PANEL_SOURCE_ROLES}
    sources = source_contract.get("sources")
    if not isinstance(sources, list):
        return result
    for source in sources:
        if isinstance(source, Mapping) and source.get("role") in result:
            source_id = source.get("source_id")
            if isinstance(source_id, str) and source_id.strip():
                result[str(source["role"])].add(source_id)
    return result


def _check(
    passed: bool, evidence_refs: list[str], details: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "passed": bool(passed),
        "evidence_refs": evidence_refs if passed else [],
        "details": deepcopy(dict(details)),
    }


def _check_passed(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("passed") is True
        and _is_string_list(value.get("evidence_refs"))
    )


def _require_mapping(
    contract: Mapping[str, Any], field: str, errors: list[str]
) -> Mapping[str, Any]:
    value = contract.get(field)
    if not isinstance(value, Mapping):
        errors.append(f"{field}_required")
        return {}
    return value


def _normalize_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = [deepcopy(dict(row)) for row in rows]
    return sorted(normalized, key=lambda row: _canonical_json(row))


def _hashable_key(value: Any) -> str:
    return _canonical_json(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _canonical_digest(
    payload: Any, *, excluded_keys: set[str] | None = None
) -> str:
    if isinstance(payload, Mapping):
        excluded = excluded_keys or set()
        content: Any = {
            key: value for key, value in payload.items() if key not in excluded
        }
    else:
        content = payload
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def _is_explicit(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed
