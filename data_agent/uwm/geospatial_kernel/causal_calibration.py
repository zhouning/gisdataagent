"""Fail-closed causal calibration contracts for the shared GWM kernel."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping


CAUSAL_CALIBRATION_CONTRACT_SCHEMA = (
    "gwm.geospatial_kernel.causal_calibration_contract.v1"
)
CAUSAL_CALIBRATION_BINDING_SCHEMA = (
    "gwm.geospatial_kernel.rollout_causal_calibration_binding.v1"
)
MAX_CLAIM_LEVEL = "bounded_action_conditioned_spatial_scenario"

_ESTIMAND_FIELDS = ("unit", "treatment_action", "outcome", "treatment_time", "horizon")
_IDENTIFICATION_FIELDS = (
    "design",
    "adjustment_set",
    "overlap",
    "consistency",
    "exchangeability_boundary",
    "interference_assumption",
    "time_varying_confounders",
)
_ESTIMATE_FIELDS = ("direct", "spillover", "total", "uncertainty")
_DIAGNOSTIC_FIELDS = (
    "balance",
    "overlap",
    "placebo",
    "negative_controls",
    "spatial_residual",
    "geographic_holdout",
    "temporal_placebo",
    "sensitivity",
)


def build_scca_causal_calibration_contract(
    *,
    estimand: Mapping[str, Any],
    spatial_exposure_mapping: Mapping[str, Any],
    identification: Mapping[str, Any],
    scca_report: Mapping[str, Any] | None = None,
    estimates: Mapping[str, Any] | None = None,
    diagnostics: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bridge Paper6/SCCA evidence into a domain-neutral GWM contract.

    SCCA is admitted only as causal diagnostic and calibration support. This
    builder intentionally cannot admit an observed policy effect for rollout.
    """

    report = deepcopy(dict(scca_report or {}))
    diagnostic_ready, readiness_basis = _scca_diagnostic_readiness(report)
    contract = {
        "schema": CAUSAL_CALIBRATION_CONTRACT_SCHEMA,
        "source_method": "paper6_scca",
        "estimand": deepcopy(dict(estimand)),
        "spatial_exposure_mapping": deepcopy(dict(spatial_exposure_mapping)),
        "identification": deepcopy(dict(identification)),
        "estimates": _normalized_estimates(estimates, report),
        "diagnostics": _normalized_diagnostics(diagnostics, report),
        "provenance": _normalized_provenance(provenance, report),
        "readiness": {
            "diagnostic_ready": diagnostic_ready,
            "diagnostic_readiness_basis": readiness_basis,
            "observed_policy_outcome_ready": False,
            "longitudinal_causal_identification_ready": False,
            "spatiotemporal_interference_identification_ready": False,
            "effect_application_admitted": False,
        },
        "admission": {
            "admissible_uses": [
                "causal_calibration_support",
                "spatial_interference_diagnostic",
                "evidence_grade_signal",
            ],
            "blocked_uses": [
                "rollout_state_effect_application",
                "identified_policy_effect_claim",
                "general_gwm_validation",
                "k0_validation",
            ],
            "required_conditions": {
                "observed_policy_outcome_ready": True,
                "identified_effect": True,
                "separate_effect_application_gate": True,
            },
            "satisfied_conditions": {
                "observed_policy_outcome_ready": False,
                "identified_effect": False,
                "separate_effect_application_gate": False,
            },
            "effect_application_admitted": False,
            "reason": "paper6_scca_is_diagnostic_evidence_not_an_effect_application_authority",
        },
        "claim_boundary": {
            "max_claim_level": MAX_CLAIM_LEVEL,
            "identified_causal_effect": False,
            "empirical_policy_effect_claim": False,
            "general_geospatial_kernel_validated": False,
            "gwm_k0_validated": False,
            "paper6_scca_replaces_world_model_simulator": False,
            "paper6_scca_replaces_domain_planner": False,
        },
    }
    contract["contract_digest"] = _canonical_digest(contract)
    return contract


def validate_causal_calibration_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate structure, hash integrity, and causal claim boundaries."""

    contract = dict(payload or {})
    errors: list[str] = []
    if contract.get("schema") != CAUSAL_CALIBRATION_CONTRACT_SCHEMA:
        errors.append("schema_mismatch")
    if contract.get("source_method") != "paper6_scca":
        errors.append("source_method_must_be_paper6_scca")

    estimand = contract.get("estimand")
    if not isinstance(estimand, Mapping):
        errors.append("estimand_required")
    else:
        for field in _ESTIMAND_FIELDS:
            if field not in estimand or not _is_explicit_value(estimand.get(field)):
                errors.append(f"estimand_{field}_required")
        if "horizon" in estimand and not _valid_horizon(estimand.get("horizon")):
            errors.append("estimand_horizon_invalid")

    exposure = contract.get("spatial_exposure_mapping")
    if not isinstance(exposure, Mapping):
        errors.append("spatial_exposure_mapping_required")
    else:
        for field in ("direct_target", "mapping_version"):
            if field not in exposure or not _is_explicit_value(exposure.get(field)):
                errors.append(f"spatial_exposure_mapping_{field}_required")
        relation_types = exposure.get("relation_types")
        if not isinstance(relation_types, list):
            errors.append("spatial_exposure_mapping_relation_types_must_be_list")
        elif any(not isinstance(value, str) or not value.strip() for value in relation_types):
            errors.append("spatial_exposure_mapping_relation_types_invalid")
        hops = exposure.get("neighborhood_hops")
        if isinstance(hops, bool) or not isinstance(hops, int) or hops < 0:
            errors.append("spatial_exposure_mapping_neighborhood_hops_invalid")

    identification = contract.get("identification")
    if not isinstance(identification, Mapping):
        errors.append("identification_required")
    else:
        for field in _IDENTIFICATION_FIELDS:
            if field not in identification or not _is_explicit_value(
                identification.get(field), allow_empty_list=field == "adjustment_set"
            ):
                errors.append(f"identification_{field}_required")
        if "adjustment_set" in identification and not isinstance(
            identification.get("adjustment_set"), list
        ):
            errors.append("identification_adjustment_set_must_be_list")
        for field in (
            "overlap",
            "consistency",
            "exchangeability_boundary",
            "interference_assumption",
            "time_varying_confounders",
        ):
            if field in identification and not isinstance(
                identification.get(field), Mapping
            ):
                errors.append(f"identification_{field}_must_be_object")

    _require_mapping_fields(contract, "estimates", _ESTIMATE_FIELDS, errors)
    _require_mapping_fields(contract, "diagnostics", _DIAGNOSTIC_FIELDS, errors)

    provenance = contract.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append("provenance_required")
    else:
        if provenance.get("source_method") != "paper6_scca":
            errors.append("provenance_source_method_mismatch")
        for field in ("source_id", "source_schema"):
            if not _is_explicit_value(provenance.get(field)):
                errors.append(f"provenance_{field}_required")
        source_digest = provenance.get("source_report_digest")
        if not _is_sha256(source_digest):
            errors.append("provenance_source_report_digest_invalid")
        if not isinstance(provenance.get("source_artifact_hashes"), Mapping):
            errors.append("provenance_source_artifact_hashes_must_be_object")
        else:
            for artifact_name, artifact_digest in provenance[
                "source_artifact_hashes"
            ].items():
                if not _is_sha256(artifact_digest):
                    errors.append(
                        f"provenance_source_artifact_hash_invalid:{artifact_name}"
                    )

    readiness = contract.get("readiness")
    if not isinstance(readiness, Mapping):
        errors.append("readiness_required")
    else:
        if not isinstance(readiness.get("diagnostic_ready"), bool):
            errors.append("diagnostic_ready_must_be_boolean")
        readiness_basis = readiness.get("diagnostic_readiness_basis")
        if not isinstance(readiness_basis, Mapping):
            errors.append("diagnostic_readiness_basis_required")
        else:
            basis_ready = any(
                readiness_basis.get(field) is True
                for field in (
                    "algorithmic_causal_diagnostic_ready",
                    "source_evidence_gate_passed",
                    "source_scca_report_passed",
                )
            )
            if readiness.get("diagnostic_ready") is not basis_ready:
                errors.append("diagnostic_ready_not_supported_by_basis")
        if readiness.get("observed_policy_outcome_ready") is not False:
            errors.append("observed_policy_outcome_ready_must_be_false")
        if readiness.get("longitudinal_causal_identification_ready") is not False:
            errors.append("longitudinal_causal_identification_ready_must_be_false")
        if (
            readiness.get("spatiotemporal_interference_identification_ready")
            is not False
        ):
            errors.append(
                "spatiotemporal_interference_identification_ready_must_be_false"
            )
        if readiness.get("effect_application_admitted") is not False:
            errors.append("readiness_effect_application_admitted_must_be_false")

    admission = contract.get("admission")
    if not isinstance(admission, Mapping):
        errors.append("admission_required")
    else:
        if admission.get("required_conditions") != {
            "observed_policy_outcome_ready": True,
            "identified_effect": True,
            "separate_effect_application_gate": True,
        }:
            errors.append("admission_required_conditions_mismatch")
        if admission.get("satisfied_conditions") != {
            "observed_policy_outcome_ready": False,
            "identified_effect": False,
            "separate_effect_application_gate": False,
        }:
            errors.append("admission_satisfied_conditions_must_all_be_false")
        if admission.get("effect_application_admitted") is not False:
            errors.append("admission_effect_application_admitted_must_be_false")

    boundary = contract.get("claim_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("claim_boundary_required")
    else:
        if boundary.get("max_claim_level") != MAX_CLAIM_LEVEL:
            errors.append("max_claim_level_exceeded")
        for field in (
            "identified_causal_effect",
            "empirical_policy_effect_claim",
            "general_geospatial_kernel_validated",
            "gwm_k0_validated",
            "paper6_scca_replaces_world_model_simulator",
            "paper6_scca_replaces_domain_planner",
        ):
            if boundary.get(field) is not False:
                errors.append(f"claim_boundary_{field}_must_be_false")

    estimates_payload = contract.get("estimates")
    if isinstance(estimates_payload, Mapping):
        for effect_name in ("direct", "spillover", "total"):
            effect = estimates_payload.get(effect_name)
            if isinstance(effect, Mapping) and effect.get("identified") is not False:
                errors.append(f"estimates_{effect_name}_identified_must_be_false")

    design_binding = contract.get("spatiotemporal_causal_design")
    extension_readiness_fields = {
        "longitudinal_design_contract_ready": "longitudinal_design_ready",
        "longitudinal_estimator_execution_ready": "estimator_execution_ready",
        "spatiotemporal_design_observed_policy_outcome_ready": (
            "observed_policy_outcome_ready"
        ),
    }
    if design_binding is not None:
        from .spatiotemporal_causal_design import (
            validate_spatiotemporal_causal_design_binding,
        )

        if not isinstance(design_binding, Mapping):
            errors.append("spatiotemporal_causal_design_binding_must_be_object")
        else:
            binding_validation = validate_spatiotemporal_causal_design_binding(
                design_binding
            )
            if not binding_validation["valid"]:
                errors.append(
                    "spatiotemporal_causal_design_binding_invalid:"
                    + str(binding_validation["errors"][0])
                )
            if isinstance(readiness, Mapping):
                for readiness_field, binding_field in (
                    extension_readiness_fields.items()
                ):
                    if readiness.get(readiness_field) is not design_binding.get(
                        binding_field
                    ):
                        errors.append(f"readiness_{readiness_field}_mismatch")
    elif isinstance(readiness, Mapping):
        for readiness_field in extension_readiness_fields:
            if readiness_field in readiness:
                errors.append(f"readiness_{readiness_field}_requires_design_binding")

    digest = contract.get("contract_digest")
    if not _is_sha256(digest):
        errors.append("contract_digest_invalid")
    elif digest != _canonical_digest(contract, excluded_keys={"contract_digest"}):
        errors.append("contract_digest_mismatch")

    return {
        "schema": "gwm.geospatial_kernel.causal_calibration_validation.v1",
        "valid": not errors,
        "errors": errors,
        "diagnostic_ready": bool((readiness or {}).get("diagnostic_ready"))
        if isinstance(readiness, Mapping)
        else False,
        "observed_policy_outcome_ready": False,
        "effect_application_admitted": False,
        "general_geospatial_kernel_validated": False,
        "gwm_k0_validated": False,
    }


def bind_causal_calibration_to_rollout(
    *,
    rollout: Mapping[str, Any],
    causal_calibration_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach diagnostic causal evidence without changing rollout trajectories."""

    validation = validate_causal_calibration_contract(causal_calibration_contract)
    if not validation["valid"]:
        raise ValueError(
            "causal_calibration_contract_invalid:" + str(validation["errors"][0])
        )
    if rollout.get("schema") != "uwm.geospatial_kernel.counterfactual_rollout.v1":
        raise ValueError("causal_calibration_rollout_schema_mismatch")

    bound = deepcopy(dict(rollout))
    core_rollout = deepcopy(bound)
    core_rollout.pop("causal_calibration", None)
    core_rollout.pop("rollout_digest", None)
    core_rollout_digest = _canonical_digest(core_rollout)
    existing_rollout_digest = rollout.get("rollout_digest")
    if (
        existing_rollout_digest is not None
        and existing_rollout_digest != core_rollout_digest
    ):
        raise ValueError("causal_calibration_rollout_digest_mismatch")
    protected_fields = {
        key: deepcopy(core_rollout.get(key))
        for key in (
            "baseline",
            "intervention",
            "alternative",
            "direct_state_delta",
            "spillover_state_delta",
        )
    }
    contract = deepcopy(dict(causal_calibration_contract))
    binding_basis = {
        "contract_digest": contract["contract_digest"],
        "core_rollout_digest": core_rollout_digest,
        "protected_rollout_fields_digest": _canonical_digest(protected_fields),
        "kernel_version": core_rollout.get("kernel_version"),
        "t0_snapshot_digest": core_rollout.get("t0_snapshot_digest"),
    }
    readiness = contract["readiness"]
    bound["causal_calibration"] = {
        "schema": CAUSAL_CALIBRATION_BINDING_SCHEMA,
        "contract": contract,
        "contract_digest": contract["contract_digest"],
        "core_rollout_digest": core_rollout_digest,
        "protected_rollout_fields_digest": binding_basis[
            "protected_rollout_fields_digest"
        ],
        "binding_digest": _canonical_digest(binding_basis),
        "diagnostic_ready": readiness["diagnostic_ready"],
        "observed_policy_outcome_ready": False,
        "effect_application_admitted": False,
        "effect_application_status": "blocked_diagnostic_only",
        "trajectory_modified": False,
        "claim_boundary": {
            "max_claim_level": MAX_CLAIM_LEVEL,
            "identified_causal_effect": False,
            "empirical_policy_effect_claim": False,
        },
    }
    bound["rollout_digest"] = _canonical_digest(
        bound, excluded_keys={"rollout_digest"}
    )
    return bound


def _scca_diagnostic_readiness(
    report: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    gate = report.get("evidence_gate")
    gate = gate if isinstance(gate, Mapping) else {}
    algorithmic_ready = report.get("algorithmic_causal_diagnostic_ready") is True
    gate_ready = gate.get("passed") is True or gate.get("status") == "pass"
    report_ready = report.get("status") == "pass" and report.get("algorithm") == "SCCA"
    ready = bool(algorithmic_ready or gate_ready or report_ready)
    return ready, {
        "source_schema": report.get("schema"),
        "algorithmic_causal_diagnostic_ready": algorithmic_ready,
        "source_evidence_gate_passed": gate_ready,
        "source_scca_report_passed": report_ready,
    }


def _normalized_estimates(
    estimates: Mapping[str, Any] | None, report: Mapping[str, Any]
) -> dict[str, Any]:
    if estimates is None:
        effect = report.get("effect")
        effect = effect if isinstance(effect, Mapping) else {}
        raw: dict[str, Any] = {
            "direct": {
                "estimate": effect.get("coef"),
                "source_field": "effect.coef",
            },
            "spillover": {
                "estimate": effect.get("neighbor_exposure_coef"),
                "source_field": "effect.neighbor_exposure_coef",
            },
            "total": {
                "estimate": None,
                "source_field": None,
                "status": "not_identified_by_bridge",
            },
            "uncertainty": {
                "ci_lower": effect.get("ci_lower"),
                "ci_upper": effect.get("ci_upper"),
                "p_value": effect.get("p_value"),
            },
        }
    else:
        raw = deepcopy(dict(estimates))
    normalized: dict[str, Any] = {}
    for field in _ESTIMATE_FIELDS:
        value = deepcopy(raw.get(field))
        if field == "uncertainty":
            normalized[field] = value if isinstance(value, Mapping) else {"value": value}
            continue
        effect = dict(value) if isinstance(value, Mapping) else {"estimate": value}
        effect["identified"] = False
        normalized[field] = effect
    return normalized


def _normalized_diagnostics(
    diagnostics: Mapping[str, Any] | None, report: Mapping[str, Any]
) -> dict[str, Any]:
    raw = deepcopy(dict(diagnostics or {}))
    if diagnostics is None:
        raw.update(
            {
                "balance": deepcopy(report.get("balance")),
                "spatial_residual": deepcopy(report.get("spatial_diagnostics")),
                "sensitivity": deepcopy(report.get("credibility")),
            }
        )
    normalized: dict[str, Any] = {}
    for field in _DIAGNOSTIC_FIELDS:
        value = deepcopy(raw.get(field))
        if value is None:
            normalized[field] = {"status": "not_available"}
        elif isinstance(value, Mapping):
            normalized[field] = dict(value)
        else:
            normalized[field] = {
                "status": "provided_unstructured",
                "value": value,
            }
    return normalized


def _normalized_provenance(
    provenance: Mapping[str, Any] | None, report: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = deepcopy(dict(provenance or {}))
    source_id = (
        normalized.get("source_id")
        or report.get("gate_id")
        or report.get("state_version_id")
        or report.get("case_id")
    )
    normalized.update(
        {
            "source_method": "paper6_scca",
            "source_id": source_id,
            "source_schema": report.get("schema")
            or normalized.get("source_schema"),
            "source_report_digest": _canonical_digest(report),
        }
    )
    hashes = normalized.get("source_artifact_hashes")
    normalized["source_artifact_hashes"] = (
        deepcopy(dict(hashes))
        if isinstance(hashes, Mapping)
        else ({"__invalid_input__": str(hashes)} if hashes is not None else {})
    )
    return normalized


def _require_mapping_fields(
    contract: Mapping[str, Any],
    section_name: str,
    fields: tuple[str, ...],
    errors: list[str],
) -> None:
    section = contract.get(section_name)
    if not isinstance(section, Mapping):
        errors.append(f"{section_name}_required")
        return
    for field in fields:
        if field not in section:
            errors.append(f"{section_name}_{field}_required")
        elif not isinstance(section.get(field), Mapping):
            errors.append(f"{section_name}_{field}_must_be_object")


def _is_explicit_value(value: Any, *, allow_empty_list: bool = False) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return allow_empty_list if not value else True
    return True


def _valid_horizon(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)


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
