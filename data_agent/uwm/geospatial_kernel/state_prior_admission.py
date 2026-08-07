"""Fail-closed admission for calibrated geospatial state-prior context."""

from __future__ import annotations

import copy
import math
from typing import Any

from ..geospatial_state_prior_benchmark import (
    REQUIRED_GEOMETRY_ROUTES,
    validate_uwm_geospatial_state_prior_benchmark,
)

STATE_PRIOR_ARTIFACT_SCHEMA = "uwm.geospatial_state_prior.context_artifact.v1"
STATE_PRIOR_ADMISSION_SCHEMA = "uwm.geospatial_kernel.state_prior_admission.v1"
STATE_PRIOR_CONTEXT_SCHEMA = "uwm.geospatial_kernel.state_prior_context.v1"

REQUIRED_READINESS_GATES = (
    "three_native_geometry_routes_present",
    "strict_holdout_leakage_audits_passed",
    "candidate_beats_required_baselines_on_every_split",
    "geometry_shuffle_negative_controls_passed",
    "dynamic_context_ablation_gate_passed",
    "dynamic_context_sample_support_gate_passed",
    "split_conformal_coverage_passed",
    "observed_holdout_evidence_present",
)

ADMISSION_GATES = (
    "benchmark_contract_valid",
    "prior_artifact_contract_valid",
    "benchmark_ready",
    "observed_holdout_evidence",
    "all_readiness_gates_passed",
    "bounded_support_claim",
    "evidence_refs_present",
    "geometry_coverage_complete",
    "uncertainty_calibrated",
    "calibration_linked",
    "target_leakage_absent",
    "claim_boundary_preserved",
)

ALLOWED_CONTEXT_USES = ("node_context", "region_context", "state_initializer")
FORBIDDEN_CONTEXT_USES = (
    "action_model",
    "forcing",
    "topology",
    "policy_effect",
    "action_conditioned_dynamics",
)

_SUPPORTED_BENCHMARK_CLAIM = "multi_geometry_state_reconstruction_advantage_under_strict_holdout"
_ADMITTED_CLAIM = "calibrated_multi_geometry_state_prior_context_admitted"
_REJECTED_CLAIM = "no_state_prior_context_admission"
_DERIVATION_KIND = "observed_holdout_state_reconstruction"
_SUPPORT_LEVEL = "learned_calibrated"
_UNCERTAINTY_REPRESENTATION = "two_sided_prediction_interval"


def validate_state_prior_artifact(artifact: Any) -> dict[str, Any]:
    """Validate a bounded, calibrated state-prior artifact before admission."""

    if not isinstance(artifact, dict):
        return {"valid": False, "errors": ["artifact_must_be_a_dictionary"]}

    errors: list[str] = []
    if artifact.get("schema") != STATE_PRIOR_ARTIFACT_SCHEMA:
        errors.append("artifact_schema_mismatch")
    for field in ("state_prior_id", "benchmark_id", "context_ref"):
        if not _nonempty_string(artifact.get(field)):
            errors.append(f"{field}_required")
    if not _valid_sha256(artifact.get("context_sha256")):
        errors.append("context_sha256_invalid")
    if artifact.get("source_evidence_kind") != "observed_holdout":
        errors.append("artifact_requires_observed_holdout_evidence")
    if artifact.get("derivation_kind") != _DERIVATION_KIND:
        errors.append("artifact_derivation_must_be_observed_holdout_state_reconstruction")
    if artifact.get("support_level") != _SUPPORT_LEVEL:
        errors.append("artifact_support_level_must_be_learned_calibrated")
    if not _nonempty_strings(artifact.get("state_variables")):
        errors.append("state_variables_missing")

    evidence_refs = artifact.get("evidence_refs")
    if not _nonempty_strings(evidence_refs):
        errors.append("artifact_evidence_refs_missing")

    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance_missing")
    else:
        for field in ("model_id", "model_version", "parameter_ref"):
            if not _nonempty_string(provenance.get(field)):
                errors.append(f"provenance_{field}_required")
        if not _nonempty_strings(provenance.get("evidence_refs")):
            errors.append("provenance_evidence_refs_missing")

    coverage = artifact.get("geometry_coverage")
    if not isinstance(coverage, dict):
        errors.append("geometry_coverage_missing")
    else:
        routes = coverage.get("routes")
        if not _nonempty_strings(routes) or not set(REQUIRED_GEOMETRY_ROUTES).issubset(routes):
            errors.append("geometry_coverage_requires_all_native_routes")
        if coverage.get("coverage_scope") != "benchmark_geometry_routes":
            errors.append("geometry_coverage_scope_must_be_benchmark_geometry_routes")

    uncertainty = artifact.get("uncertainty")
    if not isinstance(uncertainty, dict):
        errors.append("uncertainty_missing")
    else:
        if uncertainty.get("calibrated") is not True:
            errors.append("uncertainty_must_be_calibrated")
        if uncertainty.get("representation") != _UNCERTAINTY_REPRESENTATION:
            errors.append("uncertainty_representation_must_be_prediction_interval")
        if not _valid_confidence_level(uncertainty.get("confidence_level")):
            errors.append("uncertainty_confidence_level_invalid")

    calibration = artifact.get("calibration")
    if not isinstance(calibration, dict):
        errors.append("calibration_missing")
    else:
        if not _nonempty_string(calibration.get("method")):
            errors.append("calibration_method_required")
        if calibration.get("benchmark_id") != artifact.get("benchmark_id"):
            errors.append("calibration_benchmark_id_mismatch")
        if calibration.get("holdout_validated") is not True:
            errors.append("calibration_must_be_holdout_validated")
        if not _valid_confidence_level(calibration.get("confidence_level")):
            errors.append("calibration_confidence_level_invalid")
        if not _nonempty_strings(calibration.get("evidence_refs")):
            errors.append("calibration_evidence_refs_missing")

    leakage = artifact.get("target_leakage_audit")
    if not isinstance(leakage, dict):
        errors.append("target_leakage_audit_missing")
    else:
        if leakage.get("passed") is not True:
            errors.append("target_leakage_audit_must_pass")
        if leakage.get("uses_target_values") is not False:
            errors.append("target_values_must_not_be_used_as_features")
        if leakage.get("holdout_membership_used_for_fit") is not False:
            errors.append("holdout_membership_must_not_be_used_for_fit")

    if _claim_level(artifact) != "bounded_support":
        errors.append("artifact_claim_level_must_be_bounded_support")
    errors.extend(_claim_escalation_errors(artifact, prefix="artifact"))

    nested_refs: list[str] = []
    if isinstance(provenance, dict) and isinstance(provenance.get("evidence_refs"), list):
        nested_refs.extend(provenance["evidence_refs"])
    if isinstance(calibration, dict) and isinstance(calibration.get("evidence_refs"), list):
        nested_refs.extend(calibration["evidence_refs"])
    if _nonempty_strings(evidence_refs) and any(ref not in evidence_refs for ref in nested_refs):
        errors.append("nested_evidence_refs_must_be_declared_at_artifact_level")

    return {"valid": not errors, "errors": errors}


def build_state_prior_admission(
    *,
    benchmark: dict[str, Any],
    state_prior_artifact: dict[str, Any],
    admission_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Build an auditable admission result without enabling rejected context."""

    benchmark_validation = validate_uwm_geospatial_state_prior_benchmark(benchmark)
    artifact_validation = validate_state_prior_artifact(state_prior_artifact)
    readiness = benchmark.get("readiness_gates") or {}
    benchmark_calibration = benchmark.get("uncertainty_calibration") or {}
    artifact_calibration = state_prior_artifact.get("calibration") or {}
    artifact_uncertainty = state_prior_artifact.get("uncertainty") or {}
    artifact_coverage = state_prior_artifact.get("geometry_coverage") or {}

    gates = {
        "benchmark_contract_valid": benchmark_validation["valid"],
        "prior_artifact_contract_valid": artifact_validation["valid"],
        "benchmark_ready": benchmark.get("geospatial_state_prior_benchmark_ready") is True,
        "observed_holdout_evidence": (
            benchmark.get("source_evidence_kind") == "observed_holdout"
            and state_prior_artifact.get("source_evidence_kind") == "observed_holdout"
        ),
        "all_readiness_gates_passed": (
            set(readiness) == set(REQUIRED_READINESS_GATES)
            and all(readiness.get(name) is True for name in REQUIRED_READINESS_GATES)
        ),
        "bounded_support_claim": (
            _claim_level(benchmark) == "bounded_support"
            and benchmark.get("supported_claim") == _SUPPORTED_BENCHMARK_CLAIM
            and _claim_level(state_prior_artifact) == "bounded_support"
        ),
        "evidence_refs_present": (
            _nonempty_strings(benchmark.get("evidence_refs"))
            and _nonempty_strings(state_prior_artifact.get("evidence_refs"))
        ),
        "geometry_coverage_complete": _geometry_coverage_matches(benchmark, artifact_coverage),
        "uncertainty_calibrated": (
            benchmark_calibration.get("coverage_gate_passed") is True
            and artifact_uncertainty.get("calibrated") is True
            and artifact_uncertainty.get("representation") == _UNCERTAINTY_REPRESENTATION
        ),
        "calibration_linked": _calibration_matches(
            benchmark=benchmark,
            benchmark_calibration=benchmark_calibration,
            artifact=state_prior_artifact,
            artifact_calibration=artifact_calibration,
            artifact_uncertainty=artifact_uncertainty,
        ),
        "target_leakage_absent": _target_leakage_absent(benchmark, state_prior_artifact),
        "claim_boundary_preserved": (
            not _claim_escalation_errors(benchmark, prefix="benchmark")
            and not _claim_escalation_errors(state_prior_artifact, prefix="artifact")
        ),
    }
    admitted = all(gates.values())
    evidence_refs = _unique_strings(
        [
            *(benchmark.get("evidence_refs") or []),
            *(state_prior_artifact.get("evidence_refs") or []),
        ]
    )
    calibration_evidence_refs = (
        _unique_strings(artifact_calibration.get("evidence_refs") or []) if admitted else []
    )

    result = {
        "schema": STATE_PRIOR_ADMISSION_SCHEMA,
        "version": "0.1",
        "admission_id": str(admission_id),
        "created_at": str(created_at),
        "benchmark_id": str(benchmark.get("benchmark_id") or ""),
        "state_prior_id": str(state_prior_artifact.get("state_prior_id") or ""),
        "status": "admitted" if admitted else "rejected",
        "state_prior_context_ready": admitted,
        "gate_results": gates,
        "rejection_reasons": [name for name in ADMISSION_GATES if not gates[name]],
        "input_validation_errors": {
            "benchmark": list(benchmark_validation["errors"]),
            "state_prior_artifact": list(artifact_validation["errors"]),
        },
        "enabled_support_levels": [_SUPPORT_LEVEL] if admitted else [],
        "evidence_refs": evidence_refs,
        "calibration_evidence_refs": calibration_evidence_refs,
        "context_envelope": (_build_context_envelope(state_prior_artifact) if admitted else None),
        "supported_claim": _ADMITTED_CLAIM if admitted else _REJECTED_CLAIM,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if admitted else "not_for_claim",
            "scope": "state_reconstruction_context_only",
        },
        "policy_causal_effect_claim": False,
        "action_conditioned_dynamics_claim": False,
        "general_geospatial_world_model_validation_claim": False,
        "empirical_policy_effect_claim": False,
    }
    validation = validate_state_prior_admission(result)
    if not validation["valid"]:
        raise ValueError("invalid_state_prior_admission:" + ";".join(validation["errors"]))
    return result


def validate_state_prior_admission(payload: Any) -> dict[str, Any]:
    """Validate admission consistency and prohibit policy/dynamics escalation."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["admission_must_be_a_dictionary"]}

    errors: list[str] = []
    if payload.get("schema") != STATE_PRIOR_ADMISSION_SCHEMA:
        errors.append("admission_schema_mismatch")
    for field in ("admission_id", "created_at", "benchmark_id", "state_prior_id"):
        if not _nonempty_string(payload.get(field)):
            errors.append(f"{field}_required")

    gates = payload.get("gate_results")
    if not isinstance(gates, dict) or set(gates) != set(ADMISSION_GATES):
        errors.append("admission_gate_set_mismatch")
        all_gates_pass = False
    else:
        if any(not isinstance(value, bool) for value in gates.values()):
            errors.append("admission_gate_values_must_be_boolean")
        all_gates_pass = all(gates.get(name) is True for name in ADMISSION_GATES)

    admitted = payload.get("state_prior_context_ready") is True
    expected_status = "admitted" if admitted else "rejected"
    if payload.get("status") != expected_status:
        errors.append("admission_status_inconsistent")
    if admitted != all_gates_pass:
        errors.append("admission_readiness_must_equal_all_gates")

    gate_mapping = gates if isinstance(gates, dict) else {}
    expected_reasons = [name for name in ADMISSION_GATES if not gate_mapping.get(name)]
    if payload.get("rejection_reasons") != expected_reasons:
        errors.append("admission_rejection_reasons_inconsistent")
    errors.extend(_claim_escalation_errors(payload, prefix="admission"))

    if admitted:
        if payload.get("enabled_support_levels") != [_SUPPORT_LEVEL]:
            errors.append("admitted_context_must_enable_only_learned_calibrated")
        if not _nonempty_strings(payload.get("evidence_refs")):
            errors.append("admitted_context_requires_evidence_refs")
        if not _nonempty_strings(payload.get("calibration_evidence_refs")):
            errors.append("admitted_context_requires_calibration_evidence_refs")
        if payload.get("supported_claim") != _ADMITTED_CLAIM:
            errors.append("admitted_context_supported_claim_mismatch")
        if _claim_level(payload) != "bounded_support":
            errors.append("admitted_context_requires_bounded_support")
        errors.extend(_validate_context_envelope(payload.get("context_envelope")))
    else:
        if payload.get("enabled_support_levels") != []:
            errors.append("rejected_context_must_not_enable_support_levels")
        if payload.get("calibration_evidence_refs") != []:
            errors.append("rejected_context_must_not_enable_calibration_evidence")
        if payload.get("context_envelope") is not None:
            errors.append("rejected_context_envelope_must_be_null")
        if payload.get("supported_claim") != _REJECTED_CLAIM:
            errors.append("rejected_context_supported_claim_mismatch")
        if _claim_level(payload) != "not_for_claim":
            errors.append("rejected_context_must_be_not_for_claim")

    return {"valid": not errors, "errors": errors}


def _build_context_envelope(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": STATE_PRIOR_CONTEXT_SCHEMA,
        "state_prior_id": artifact["state_prior_id"],
        "context_ref": artifact["context_ref"],
        "context_sha256": artifact["context_sha256"],
        "state_variables": list(artifact["state_variables"]),
        "support_level": _SUPPORT_LEVEL,
        "allowed_uses": list(ALLOWED_CONTEXT_USES),
        "forbidden_uses": list(FORBIDDEN_CONTEXT_USES),
        "provenance": copy.deepcopy(artifact["provenance"]),
        "geometry_coverage": copy.deepcopy(artifact["geometry_coverage"]),
        "uncertainty": copy.deepcopy(artifact["uncertainty"]),
        "calibration": copy.deepcopy(artifact["calibration"]),
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "scope": "state_reconstruction_context_only",
        },
        "policy_causal_effect_claim": False,
        "action_conditioned_dynamics_claim": False,
    }


def _validate_context_envelope(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["admitted_context_envelope_required"]
    errors: list[str] = []
    if value.get("schema") != STATE_PRIOR_CONTEXT_SCHEMA:
        errors.append("context_envelope_schema_mismatch")
    if value.get("support_level") != _SUPPORT_LEVEL:
        errors.append("context_envelope_support_level_mismatch")
    if not _valid_sha256(value.get("context_sha256")):
        errors.append("context_envelope_sha256_invalid")
    if value.get("allowed_uses") != list(ALLOWED_CONTEXT_USES):
        errors.append("context_envelope_allowed_uses_mismatch")
    if value.get("forbidden_uses") != list(FORBIDDEN_CONTEXT_USES):
        errors.append("context_envelope_forbidden_uses_mismatch")
    if _claim_level(value) != "bounded_support":
        errors.append("context_envelope_claim_level_mismatch")
    errors.extend(_claim_escalation_errors(value, prefix="context_envelope"))
    return errors


def _geometry_coverage_matches(benchmark: dict[str, Any], coverage: dict[str, Any]) -> bool:
    if not isinstance(coverage, dict):
        return False
    benchmark_routes = set((benchmark.get("geometry_routes") or {}).keys())
    artifact_routes = coverage.get("routes") or []
    return (
        set(REQUIRED_GEOMETRY_ROUTES).issubset(benchmark_routes)
        and _nonempty_strings(artifact_routes)
        and benchmark_routes.issubset(set(artifact_routes))
        and coverage.get("coverage_scope") == "benchmark_geometry_routes"
    )


def _calibration_matches(
    *,
    benchmark: dict[str, Any],
    benchmark_calibration: dict[str, Any],
    artifact: dict[str, Any],
    artifact_calibration: dict[str, Any],
    artifact_uncertainty: dict[str, Any],
) -> bool:
    benchmark_confidence = benchmark_calibration.get("confidence_level")
    artifact_confidence = artifact_calibration.get("confidence_level")
    uncertainty_confidence = artifact_uncertainty.get("confidence_level")
    return (
        artifact.get("benchmark_id") == benchmark.get("benchmark_id")
        and artifact_calibration.get("benchmark_id") == benchmark.get("benchmark_id")
        and artifact_calibration.get("method") == benchmark_calibration.get("method")
        and artifact_calibration.get("holdout_validated") is True
        and _nonempty_strings(artifact_calibration.get("evidence_refs"))
        and _same_number(benchmark_confidence, artifact_confidence)
        and _same_number(benchmark_confidence, uncertainty_confidence)
    )


def _target_leakage_absent(benchmark: dict[str, Any], artifact: dict[str, Any]) -> bool:
    split_results = benchmark.get("split_results") or {}
    split_audits_pass = bool(split_results) and all(
        (result.get("leakage_audit") or {}).get("passed") is True
        for result in split_results.values()
        if isinstance(result, dict)
    )
    dynamic_context = benchmark.get("dynamic_context")
    dynamic_context_safe = not dynamic_context or (
        isinstance(dynamic_context, dict) and dynamic_context.get("uses_target_values") is False
    )
    artifact_audit = artifact.get("target_leakage_audit") or {}
    return (
        split_audits_pass
        and dynamic_context_safe
        and artifact_audit.get("passed") is True
        and artifact_audit.get("uses_target_values") is False
        and artifact_audit.get("holdout_membership_used_for_fit") is False
    )


def _claim_escalation_errors(payload: dict[str, Any], *, prefix: str) -> list[str]:
    errors = []
    for field in (
        "policy_causal_effect_claim",
        "action_conditioned_dynamics_claim",
        "general_geospatial_world_model_validation_claim",
        "empirical_policy_effect_claim",
    ):
        if payload.get(field, False) is not False:
            errors.append(f"{prefix}_{field}_must_be_false")
    return errors


def _claim_level(payload: dict[str, Any]) -> Any:
    boundary = payload.get("claim_boundary")
    return boundary.get("max_claim_level") if isinstance(boundary, dict) else None


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_nonempty_string(item) for item in value)


def _unique_strings(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if _nonempty_string(value)))


def _valid_confidence_level(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0.0 < float(value) < 1.0
    )


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _same_number(left: Any, right: Any) -> bool:
    return (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
        and math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
    )
