"""Longitudinal spatial causal design contracts for the shared GWM kernel."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from typing import Any, Mapping


SPATIOTEMPORAL_CAUSAL_DESIGN_SCHEMA = (
    "gwm.geospatial_kernel.spatiotemporal_causal_design.v1"
)
SPATIOTEMPORAL_CAUSAL_BINDING_SCHEMA = (
    "gwm.geospatial_kernel.spatiotemporal_causal_design_binding.v1"
)

LONGITUDINAL_DESIGN_GATES = (
    "unit_time_index_unique",
    "temporal_order_verified",
    "treatment_precedes_outcome",
    "pre_treatment_covariates_verified",
    "time_varying_confounders_measured",
    "treatment_confounder_feedback_declared",
    "positivity_by_time_diagnosed",
    "censoring_and_missingness_diagnosed",
    "interference_exposure_mapping_versioned",
    "network_time_alignment_verified",
    "no_future_information_leakage",
)
LONGITUDINAL_ESTIMATION_GATES = (
    "longitudinal_estimator_executed",
    "sequential_balance_passed",
    "weight_stability_passed",
    "pretrend_or_preperiod_stability_passed",
    "temporal_placebo_passed",
    "geographic_holdout_passed",
    "uncertainty_estimated",
    "observed_policy_outcome_available",
)
SPATIOTEMPORAL_INTERFERENCE_GATES = (
    "interference_exposure_mapping_versioned",
    "network_time_alignment_verified",
    "no_future_information_leakage",
)

_TREATMENT_TYPES = {
    "point_intervention_with_longitudinal_outcomes",
    "time_varying_treatment",
    "dynamic_treatment_regime",
}
_FEEDBACK_STATUSES = {
    "absent_by_design",
    "present_measured",
    "present_unmeasured",
    "unknown",
}
_NETWORK_TIME_MODES = {"fixed_at_baseline", "lagged_dynamic"}
_IDENTIFICATION_STRATEGIES = {
    "marginal_structural_model_ipw",
    "longitudinal_g_formula",
    "sequential_aipw",
    "longitudinal_tmle",
    "event_study_with_spatial_interference_diagnostics",
}


def build_spatiotemporal_causal_design_contract(
    *,
    study: Mapping[str, Any],
    estimand: Mapping[str, Any],
    panel_design: Mapping[str, Any],
    temporal_ordering: Mapping[str, Any],
    interference_mapping: Mapping[str, Any],
    identification: Mapping[str, Any],
    gate_evidence: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a non-compensatory longitudinal causal design contract."""

    normalized_gates = _normalize_gate_evidence(gate_evidence)
    sections = {
        "study": deepcopy(dict(study)),
        "estimand": deepcopy(dict(estimand)),
        "panel_design": deepcopy(dict(panel_design)),
        "temporal_ordering": deepcopy(dict(temporal_ordering)),
        "interference_mapping": deepcopy(dict(interference_mapping)),
        "identification": deepcopy(dict(identification)),
    }
    readiness = _assess_readiness(sections, normalized_gates)
    contract = {
        "schema": SPATIOTEMPORAL_CAUSAL_DESIGN_SCHEMA,
        **sections,
        "gate_evidence": normalized_gates,
        "provenance": deepcopy(dict(provenance)),
        "readiness": readiness,
        "admission": {
            "aggregation": "non_compensatory_all_required_gates",
            "design_evidence_admitted": readiness["longitudinal_design_ready"],
            "estimator_evidence_admitted": readiness["estimator_execution_ready"],
            "effect_application_admitted": False,
            "effect_application_reason": (
                "separate_hash_bound_effect_application_gate_not_implemented"
            ),
        },
        "claim_boundary": {
            "identified_policy_effect": False,
            "empirical_policy_effect_claim": False,
            "general_geospatial_kernel_validated": False,
            "gwm_k0_validated": False,
            "domain_generalization_validated": False,
        },
    }
    contract["contract_digest"] = _canonical_digest(contract)
    return contract


def validate_spatiotemporal_causal_design_contract(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate longitudinal design semantics, evidence, and claim boundaries."""

    contract = dict(payload or {})
    errors: list[str] = []
    if contract.get("schema") != SPATIOTEMPORAL_CAUSAL_DESIGN_SCHEMA:
        errors.append("schema_mismatch")

    study = _require_section(contract, "study", errors)
    _require_explicit_fields(
        study,
        "study",
        (
            "study_id",
            "domain_instance",
            "unit_id_field",
            "time_field",
            "timezone",
            "cadence",
            "observation_start",
            "observation_end",
        ),
        errors,
    )
    if study.get("unit_id_field") == study.get("time_field"):
        errors.append("study_unit_and_time_fields_must_differ")
    observation_start = _parse_timestamp(study.get("observation_start"))
    observation_end = _parse_timestamp(study.get("observation_end"))
    if observation_start is None:
        errors.append("study_observation_start_invalid")
    if observation_end is None:
        errors.append("study_observation_end_invalid")
    if (
        observation_start is not None
        and observation_end is not None
        and observation_start >= observation_end
    ):
        errors.append("study_observation_window_invalid")

    estimand = _require_section(contract, "estimand", errors)
    _require_explicit_fields(
        estimand,
        "estimand",
        (
            "treatment_strategy",
            "outcome",
            "horizon",
            "contrast",
            "target_population",
        ),
        errors,
    )
    _validate_positive_window(estimand.get("horizon"), "estimand_horizon", errors)

    panel = _require_section(contract, "panel_design", errors)
    _require_explicit_fields(
        panel,
        "panel_design",
        (
            "treatment_type",
            "treatment_field",
            "outcome_field",
            "baseline_confounders",
            "time_varying_confounders",
            "treatment_affected_confounders",
            "treatment_confounder_feedback",
            "censoring_indicator",
            "missingness_strategy",
        ),
        errors,
        allow_empty_lists={
            "time_varying_confounders",
            "treatment_affected_confounders",
        },
    )
    treatment_type = panel.get("treatment_type")
    if treatment_type not in _TREATMENT_TYPES:
        errors.append("panel_design_treatment_type_invalid")
    feedback = panel.get("treatment_confounder_feedback")
    if feedback not in _FEEDBACK_STATUSES:
        errors.append("panel_design_treatment_confounder_feedback_invalid")
    for field in ("baseline_confounders",):
        if field in panel and not _is_string_list(panel.get(field)):
            errors.append(f"panel_design_{field}_must_be_string_list")
    for field in ("time_varying_confounders", "treatment_affected_confounders"):
        if field in panel and not _is_string_list(
            panel.get(field), allow_empty=True
        ):
            errors.append(f"panel_design_{field}_must_be_string_list")
    if treatment_type in {"time_varying_treatment", "dynamic_treatment_regime"}:
        if not panel.get("time_varying_confounders"):
            errors.append("time_varying_treatment_requires_time_varying_confounders")
    if feedback == "present_measured" and not panel.get(
        "treatment_affected_confounders"
    ):
        errors.append(
            "present_measured_feedback_requires_treatment_affected_confounders"
        )
    if feedback == "absent_by_design" and panel.get("treatment_affected_confounders"):
        errors.append(
            "absent_feedback_requires_empty_treatment_affected_confounders"
        )
    if panel.get("treatment_field") == panel.get("outcome_field"):
        errors.append("panel_design_treatment_and_outcome_fields_must_differ")

    ordering = _require_section(contract, "temporal_ordering", errors)
    _require_explicit_fields(
        ordering,
        "temporal_ordering",
        (
            "confounder_measurement",
            "treatment_measurement",
            "outcome_measurement",
            "lag_definition",
            "pre_period_count",
            "post_period_count",
        ),
        errors,
    )
    expected_ordering = {
        "confounder_measurement": "before_treatment_at_each_time",
        "treatment_measurement": "after_confounders_before_outcome",
        "outcome_measurement": "after_treatment",
    }
    for field, expected in expected_ordering.items():
        if field in ordering and ordering.get(field) != expected:
            errors.append(f"temporal_ordering_{field}_invalid")
    for field in ("pre_period_count", "post_period_count"):
        value = ordering.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            errors.append(f"temporal_ordering_{field}_invalid")

    interference = _require_section(contract, "interference_mapping", errors)
    _require_explicit_fields(
        interference,
        "interference_mapping",
        (
            "direct_exposure",
            "neighbor_exposure",
            "relation_types",
            "neighborhood_hops",
            "network_time_mode",
            "mapping_version",
            "partial_interference_clusters",
            "exposure_history_window",
        ),
        errors,
    )
    if not _is_string_list(interference.get("relation_types")):
        errors.append("interference_mapping_relation_types_must_be_string_list")
    hops = interference.get("neighborhood_hops")
    if isinstance(hops, bool) or not isinstance(hops, int) or hops < 1:
        errors.append("interference_mapping_neighborhood_hops_invalid")
    if interference.get("network_time_mode") not in _NETWORK_TIME_MODES:
        errors.append("interference_mapping_network_time_mode_invalid")
    if not isinstance(interference.get("partial_interference_clusters"), Mapping):
        errors.append("interference_mapping_partial_interference_clusters_must_be_object")
    _validate_positive_window(
        interference.get("exposure_history_window"),
        "interference_mapping_exposure_history_window",
        errors,
    )

    identification = _require_section(contract, "identification", errors)
    _require_explicit_fields(
        identification,
        "identification",
        (
            "strategy",
            "sequential_exchangeability_boundary",
            "positivity_boundary",
            "consistency_boundary",
            "interference_boundary",
        ),
        errors,
    )
    if identification.get("strategy") not in _IDENTIFICATION_STRATEGIES:
        errors.append("identification_strategy_invalid")
    for field in (
        "sequential_exchangeability_boundary",
        "positivity_boundary",
        "consistency_boundary",
        "interference_boundary",
    ):
        if field in identification and not isinstance(
            identification.get(field), Mapping
        ):
            errors.append(f"identification_{field}_must_be_object")

    gates = contract.get("gate_evidence")
    if not isinstance(gates, Mapping):
        errors.append("gate_evidence_required")
        gates = {}
    for gate_name in (*LONGITUDINAL_DESIGN_GATES, *LONGITUDINAL_ESTIMATION_GATES):
        gate = gates.get(gate_name)
        if not isinstance(gate, Mapping):
            errors.append(f"gate_evidence_{gate_name}_required")
            continue
        if not isinstance(gate.get("passed"), bool):
            errors.append(f"gate_evidence_{gate_name}_passed_must_be_boolean")
        refs = gate.get("evidence_refs")
        if not _is_string_list(refs, allow_empty=True):
            errors.append(f"gate_evidence_{gate_name}_refs_must_be_string_list")
        elif gate.get("passed") is True and not refs:
            errors.append(f"gate_evidence_{gate_name}_passed_requires_evidence_refs")

    provenance = _require_section(contract, "provenance", errors)
    _require_explicit_fields(
        provenance,
        "provenance",
        ("source_bundle_id", "source_bundle_schema", "source_bundle_sha256"),
        errors,
    )
    if not _is_sha256(provenance.get("source_bundle_sha256")):
        errors.append("provenance_source_bundle_sha256_invalid")
    artifact_hashes = provenance.get("source_artifact_hashes")
    if not isinstance(artifact_hashes, Mapping):
        errors.append("provenance_source_artifact_hashes_must_be_object")
    else:
        if not artifact_hashes:
            errors.append("provenance_source_artifact_hashes_required")
        for name, digest in artifact_hashes.items():
            if not _is_sha256(digest):
                errors.append(f"provenance_source_artifact_hash_invalid:{name}")

    sections = {
        "study": study,
        "estimand": estimand,
        "panel_design": panel,
        "temporal_ordering": ordering,
        "interference_mapping": interference,
        "identification": identification,
    }
    expected_readiness = _assess_readiness(sections, gates)
    if contract.get("readiness") != expected_readiness:
        errors.append("readiness_not_reproducible_from_contract")

    admission = contract.get("admission")
    if not isinstance(admission, Mapping):
        errors.append("admission_required")
    else:
        if admission.get("aggregation") != "non_compensatory_all_required_gates":
            errors.append("admission_aggregation_must_be_non_compensatory")
        if admission.get("design_evidence_admitted") is not expected_readiness[
            "longitudinal_design_ready"
        ]:
            errors.append("admission_design_evidence_not_reproducible")
        if admission.get("estimator_evidence_admitted") is not expected_readiness[
            "estimator_execution_ready"
        ]:
            errors.append("admission_estimator_evidence_not_reproducible")
        if admission.get("effect_application_admitted") is not False:
            errors.append("admission_effect_application_admitted_must_be_false")

    boundary = contract.get("claim_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("claim_boundary_required")
    else:
        for field in (
            "identified_policy_effect",
            "empirical_policy_effect_claim",
            "general_geospatial_kernel_validated",
            "gwm_k0_validated",
            "domain_generalization_validated",
        ):
            if boundary.get(field) is not False:
                errors.append(f"claim_boundary_{field}_must_be_false")

    digest = contract.get("contract_digest")
    if not _is_sha256(digest):
        errors.append("contract_digest_invalid")
    elif digest != _canonical_digest(contract, excluded_keys={"contract_digest"}):
        errors.append("contract_digest_mismatch")

    return {
        "schema": "gwm.geospatial_kernel.spatiotemporal_causal_design_validation.v1",
        "valid": not errors,
        "errors": errors,
        **expected_readiness,
        "effect_application_admitted": False,
        "general_geospatial_kernel_validated": False,
        "gwm_k0_validated": False,
    }


def bind_spatiotemporal_design_to_causal_calibration(
    *,
    causal_calibration_contract: Mapping[str, Any],
    spatiotemporal_design_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind longitudinal design evidence without upgrading causal claims."""

    from .causal_calibration import validate_causal_calibration_contract

    causal_validation = validate_causal_calibration_contract(
        causal_calibration_contract
    )
    if not causal_validation["valid"]:
        raise ValueError(
            "causal_calibration_contract_invalid:"
            + str(causal_validation["errors"][0])
        )
    design_validation = validate_spatiotemporal_causal_design_contract(
        spatiotemporal_design_contract
    )
    if not design_validation["valid"]:
        raise ValueError(
            "spatiotemporal_causal_design_contract_invalid:"
            + str(design_validation["errors"][0])
        )
    if "spatiotemporal_causal_design" in causal_calibration_contract:
        raise ValueError("spatiotemporal_causal_design_already_bound")

    bound = deepcopy(dict(causal_calibration_contract))
    source_digest = str(bound.pop("contract_digest"))
    design = deepcopy(dict(spatiotemporal_design_contract))
    binding_basis = {
        "source_causal_contract_digest": source_digest,
        "design_contract_digest": design["contract_digest"],
    }
    bound["spatiotemporal_causal_design"] = {
        "schema": SPATIOTEMPORAL_CAUSAL_BINDING_SCHEMA,
        "design_contract": design,
        "design_contract_digest": design["contract_digest"],
        "source_causal_contract_digest": source_digest,
        "binding_digest": _canonical_digest(binding_basis),
        "longitudinal_design_ready": design_validation[
            "longitudinal_design_ready"
        ],
        "spatiotemporal_interference_design_ready": design_validation[
            "spatiotemporal_interference_design_ready"
        ],
        "estimator_execution_ready": design_validation[
            "estimator_execution_ready"
        ],
        "observed_policy_outcome_ready": design_validation[
            "observed_policy_outcome_ready"
        ],
        "effect_application_admitted": False,
    }
    bound["readiness"]["longitudinal_design_contract_ready"] = design_validation[
        "longitudinal_design_ready"
    ]
    bound["readiness"][
        "longitudinal_estimator_execution_ready"
    ] = design_validation["estimator_execution_ready"]
    bound["readiness"][
        "spatiotemporal_design_observed_policy_outcome_ready"
    ] = design_validation["observed_policy_outcome_ready"]
    bound["contract_digest"] = _canonical_digest(bound)
    return bound


def validate_spatiotemporal_causal_design_binding(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the nested binding used by a causal calibration contract."""

    binding = dict(payload or {})
    errors: list[str] = []
    if binding.get("schema") != SPATIOTEMPORAL_CAUSAL_BINDING_SCHEMA:
        errors.append("schema_mismatch")
    design = binding.get("design_contract")
    if not isinstance(design, Mapping):
        errors.append("design_contract_required")
        design_validation = {
            "valid": False,
            "longitudinal_design_ready": False,
            "spatiotemporal_interference_design_ready": False,
            "estimator_execution_ready": False,
            "observed_policy_outcome_ready": False,
        }
    else:
        design_validation = validate_spatiotemporal_causal_design_contract(design)
        if not design_validation["valid"]:
            errors.append("design_contract_invalid")
    design_digest = binding.get("design_contract_digest")
    if not _is_sha256(design_digest):
        errors.append("design_contract_digest_invalid")
    elif isinstance(design, Mapping) and design_digest != design.get(
        "contract_digest"
    ):
        errors.append("design_contract_digest_mismatch")
    source_digest = binding.get("source_causal_contract_digest")
    if not _is_sha256(source_digest):
        errors.append("source_causal_contract_digest_invalid")
    if _is_sha256(source_digest) and _is_sha256(design_digest):
        expected_binding_digest = _canonical_digest(
            {
                "source_causal_contract_digest": source_digest,
                "design_contract_digest": design_digest,
            }
        )
        if binding.get("binding_digest") != expected_binding_digest:
            errors.append("binding_digest_mismatch")
    for field in (
        "longitudinal_design_ready",
        "spatiotemporal_interference_design_ready",
        "estimator_execution_ready",
        "observed_policy_outcome_ready",
    ):
        if binding.get(field) is not design_validation.get(field):
            errors.append(f"{field}_mismatch")
    if binding.get("effect_application_admitted") is not False:
        errors.append("effect_application_admitted_must_be_false")
    return {"valid": not errors, "errors": errors}


def _normalize_gate_evidence(
    gate_evidence: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for gate_name in (*LONGITUDINAL_DESIGN_GATES, *LONGITUDINAL_ESTIMATION_GATES):
        raw = gate_evidence.get(gate_name)
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


def _assess_readiness(
    sections: Mapping[str, Mapping[str, Any]],
    gates: Mapping[str, Any],
) -> dict[str, Any]:
    structural_blockers = _structural_blockers(sections)

    def gate_passed(name: str) -> bool:
        gate = gates.get(name)
        return bool(
            isinstance(gate, Mapping)
            and gate.get("passed") is True
            and _is_string_list(gate.get("evidence_refs"))
        )

    blocking_design_gates = [
        name for name in LONGITUDINAL_DESIGN_GATES if not gate_passed(name)
    ]
    blocking_estimation_gates = [
        name for name in LONGITUDINAL_ESTIMATION_GATES if not gate_passed(name)
    ]
    design_ready = not structural_blockers and not blocking_design_gates
    interference_ready = not structural_blockers and all(
        gate_passed(name) for name in SPATIOTEMPORAL_INTERFERENCE_GATES
    )
    estimator_ready = design_ready and not blocking_estimation_gates
    return {
        "longitudinal_design_ready": design_ready,
        "spatiotemporal_interference_design_ready": interference_ready,
        "estimator_execution_ready": estimator_ready,
        "observed_policy_outcome_ready": gate_passed(
            "observed_policy_outcome_available"
        ),
        "structural_blockers": structural_blockers,
        "blocking_design_gates": blocking_design_gates,
        "blocking_estimation_gates": blocking_estimation_gates,
    }


def _structural_blockers(
    sections: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    panel = sections.get("panel_design") or {}
    ordering = sections.get("temporal_ordering") or {}
    interference = sections.get("interference_mapping") or {}
    identification = sections.get("identification") or {}
    if panel.get("treatment_type") not in _TREATMENT_TYPES:
        blockers.append("invalid_treatment_type")
    if panel.get("treatment_confounder_feedback") in {"present_unmeasured", "unknown"}:
        blockers.append("treatment_confounder_feedback_not_resolved")
    if panel.get("treatment_confounder_feedback") == "present_measured" and not panel.get(
        "treatment_affected_confounders"
    ):
        blockers.append("treatment_affected_confounders_missing")
    if panel.get("treatment_confounder_feedback") == "absent_by_design" and panel.get(
        "treatment_affected_confounders"
    ):
        blockers.append("treatment_affected_confounders_conflict_with_absent_feedback")
    if panel.get("treatment_type") in {
        "time_varying_treatment",
        "dynamic_treatment_regime",
    } and not panel.get("time_varying_confounders"):
        blockers.append("time_varying_confounders_missing")
    if ordering.get("confounder_measurement") != "before_treatment_at_each_time":
        blockers.append("confounder_temporal_order_invalid")
    if ordering.get("treatment_measurement") != "after_confounders_before_outcome":
        blockers.append("treatment_temporal_order_invalid")
    if ordering.get("outcome_measurement") != "after_treatment":
        blockers.append("outcome_temporal_order_invalid")
    for field in ("pre_period_count", "post_period_count"):
        value = ordering.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            blockers.append(f"{field}_insufficient")
    if interference.get("network_time_mode") not in _NETWORK_TIME_MODES:
        blockers.append("network_time_mode_invalid")
    if identification.get("strategy") not in _IDENTIFICATION_STRATEGIES:
        blockers.append("identification_strategy_invalid")
    return sorted(set(blockers))


def _require_section(
    contract: Mapping[str, Any], name: str, errors: list[str]
) -> Mapping[str, Any]:
    section = contract.get(name)
    if not isinstance(section, Mapping):
        errors.append(f"{name}_required")
        return {}
    return section


def _require_explicit_fields(
    section: Mapping[str, Any],
    section_name: str,
    fields: tuple[str, ...],
    errors: list[str],
    *,
    allow_empty_lists: set[str] | None = None,
) -> None:
    allowed = allow_empty_lists or set()
    for field in fields:
        if field not in section or not _is_explicit(
            section.get(field), allow_empty_list=field in allowed
        ):
            errors.append(f"{section_name}_{field}_required")


def _is_explicit(value: Any, *, allow_empty_list: bool = False) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return allow_empty_list if not value else True
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


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _validate_positive_window(
    value: Any, field_name: str, errors: list[str]
) -> None:
    if not isinstance(value, Mapping):
        errors.append(f"{field_name}_must_be_object")
        return
    periods = value.get("periods")
    if isinstance(periods, bool) or not isinstance(periods, int) or periods < 1:
        errors.append(f"{field_name}_periods_invalid")
    if not isinstance(value.get("unit"), str) or not value["unit"].strip():
        errors.append(f"{field_name}_unit_required")


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
