"""Longitudinal causal diagnostics for the shared GWM kernel."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from .longitudinal_panel_validation import (
    seed_spatiotemporal_gate_evidence_from_panel_validation,
    validate_longitudinal_panel_validation_contract,
)
from .spatiotemporal_causal_design import (
    LONGITUDINAL_DESIGN_GATES,
    LONGITUDINAL_ESTIMATION_GATES,
)


LONGITUDINAL_CAUSAL_DIAGNOSTIC_SCHEMA = (
    "gwm.geospatial_kernel.longitudinal_causal_diagnostics.v1"
)
LONGITUDINAL_CAUSAL_DIAGNOSTIC_CHECKS = (
    "panel_rows_hash_bound",
    "diagnostic_index_unique_complete",
    "diagnostic_values_finite",
    "nuisance_cross_fitting_verified",
    "weight_formula_consistency_verified",
    "positivity_by_time_passed",
    "sequential_balance_passed",
    "treatment_weight_stability_passed",
    "censoring_diagnostic_passed",
    "combined_weight_stability_passed",
)
LONGITUDINAL_DIAGNOSTIC_EXECUTION_CHECKS = (
    "panel_rows_hash_bound",
    "diagnostic_index_unique_complete",
    "diagnostic_values_finite",
    "nuisance_cross_fitting_verified",
    "weight_formula_consistency_verified",
)
LONGITUDINAL_DIAGNOSTIC_THRESHOLD_CHECKS = (
    "positivity_by_time_passed",
    "sequential_balance_passed",
    "treatment_weight_stability_passed",
    "censoring_diagnostic_passed",
    "combined_weight_stability_passed",
)

_WEIGHTING_ESTIMANDS = {"ate", "att", "dynamic_regime"}
_RISK_SETS = {"all_panel_rows"}


def build_longitudinal_causal_diagnostic_contract(
    *,
    panel_validation_contract: Mapping[str, Any],
    panel_rows: Sequence[Mapping[str, Any]],
    diagnostic_rows: Sequence[Mapping[str, Any]],
    field_mapping: Mapping[str, Any],
    analysis: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute diagnostics without estimating or applying an outcome effect."""

    panel_contract = deepcopy(dict(panel_validation_contract))
    normalized_panel = _normalize_rows(panel_rows)
    normalized_diagnostics = _normalize_rows(diagnostic_rows)
    mapping = deepcopy(dict(field_mapping))
    analysis_section = deepcopy(dict(analysis))
    threshold_section = deepcopy(dict(thresholds))
    provenance_section = deepcopy(dict(provenance))
    manifest = {
        "panel_row_count": len(normalized_panel),
        "diagnostic_row_count": len(normalized_diagnostics),
        "panel_rows_sha256": _canonical_digest(normalized_panel),
        "diagnostic_rows_sha256": _canonical_digest(normalized_diagnostics),
    }
    checks = _compute_diagnostics(
        panel_validation_contract=panel_contract,
        panel_rows=normalized_panel,
        diagnostic_rows=normalized_diagnostics,
        field_mapping=mapping,
        analysis=analysis_section,
        thresholds=threshold_section,
        manifest=manifest,
    )
    readiness = _assess_readiness(
        panel_validation_contract=panel_contract,
        checks=checks,
    )
    contract = {
        "schema": LONGITUDINAL_CAUSAL_DIAGNOSTIC_SCHEMA,
        "panel_validation_contract": panel_contract,
        "panel_validation_contract_digest": panel_contract.get(
            "contract_digest"
        ),
        "field_mapping": mapping,
        "analysis": analysis_section,
        "thresholds": threshold_section,
        "provenance": provenance_section,
        "manifest": manifest,
        "checks": checks,
        "readiness": readiness,
        "admission": {
            "aggregation": "non_compensatory_panel_binding_execution_and_thresholds",
            "diagnostic_execution_admitted": readiness[
                "empirical_diagnostic_evidence_ready"
            ],
            "all_diagnostic_thresholds_admitted": readiness[
                "all_diagnostic_thresholds_passed"
            ],
            "longitudinal_estimator_admitted": False,
            "causal_estimation_admitted": False,
            "effect_application_admitted": False,
        },
        "claim_boundary": {
            "diagnostic_weights_not_outcome_estimator": True,
            "diagnostic_pass_not_exchangeability_proof": True,
            "synthetic_diagnostics_not_empirical_evidence": True,
            "identified_policy_effect": False,
            "empirical_policy_effect_claim": False,
            "general_geospatial_kernel_validated": False,
            "gwm_k0_validated": False,
        },
    }
    contract["contract_digest"] = _canonical_digest(contract)
    return contract


def validate_longitudinal_causal_diagnostic_contract(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate diagnostic structure, bindings, metrics, and claim boundaries."""

    contract = dict(payload or {})
    errors: list[str] = []
    if contract.get("schema") != LONGITUDINAL_CAUSAL_DIAGNOSTIC_SCHEMA:
        errors.append("schema_mismatch")

    panel_contract = contract.get("panel_validation_contract")
    if not isinstance(panel_contract, Mapping):
        errors.append("panel_validation_contract_required")
        panel_contract = {}
    panel_validation = validate_longitudinal_panel_validation_contract(
        panel_contract
    )
    if not panel_validation["valid"]:
        errors.append("panel_validation_contract_invalid")
    if contract.get("panel_validation_contract_digest") != panel_contract.get(
        "contract_digest"
    ):
        errors.append("panel_validation_contract_digest_mismatch")

    mapping = _require_mapping(contract, "field_mapping", errors)
    _validate_field_mapping(mapping, errors)
    analysis = _require_mapping(contract, "analysis", errors)
    _validate_analysis(analysis, panel_contract, errors)
    thresholds = _require_mapping(contract, "thresholds", errors)
    _validate_thresholds(thresholds, errors)
    provenance = _require_mapping(contract, "provenance", errors)
    _validate_provenance(provenance, errors)

    manifest = _require_mapping(contract, "manifest", errors)
    for field in ("panel_row_count", "diagnostic_row_count"):
        value = manifest.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"manifest_{field}_invalid")
    for field in ("panel_rows_sha256", "diagnostic_rows_sha256"):
        if not _is_sha256(manifest.get(field)):
            errors.append(f"manifest_{field}_invalid")

    checks = contract.get("checks")
    if not isinstance(checks, Mapping):
        errors.append("checks_required")
        checks = {}
    allowed_refs = {
        "panel_rows_sha256:" + str(manifest.get("panel_rows_sha256")),
        "diagnostic_rows_sha256:" + str(
            manifest.get("diagnostic_rows_sha256")
        ),
        "panel_validation_contract:"
        + str(contract.get("panel_validation_contract_digest")),
    }
    for check_name in LONGITUDINAL_CAUSAL_DIAGNOSTIC_CHECKS:
        check = checks.get(check_name)
        if not isinstance(check, Mapping):
            errors.append(f"checks_{check_name}_required")
            continue
        if not isinstance(check.get("passed"), bool):
            errors.append(f"checks_{check_name}_passed_must_be_boolean")
        refs = check.get("evidence_refs")
        if not _is_string_list(refs):
            errors.append(f"checks_{check_name}_refs_must_be_string_list")
        elif any(ref not in allowed_refs for ref in refs):
            errors.append(f"checks_{check_name}_evidence_ref_not_bound")
        if not isinstance(check.get("details"), Mapping):
            errors.append(f"checks_{check_name}_details_must_be_object")

    expected_readiness = _assess_readiness(
        panel_validation_contract=panel_contract,
        checks=checks,
    )
    if contract.get("readiness") != expected_readiness:
        errors.append("readiness_not_reproducible_from_contract")

    admission = contract.get("admission")
    if not isinstance(admission, Mapping):
        errors.append("admission_required")
    else:
        if admission.get("aggregation") != (
            "non_compensatory_panel_binding_execution_and_thresholds"
        ):
            errors.append("admission_aggregation_invalid")
        if admission.get(
            "diagnostic_execution_admitted"
        ) is not expected_readiness["empirical_diagnostic_evidence_ready"]:
            errors.append("admission_diagnostic_execution_not_reproducible")
        if admission.get(
            "all_diagnostic_thresholds_admitted"
        ) is not expected_readiness["all_diagnostic_thresholds_passed"]:
            errors.append("admission_thresholds_not_reproducible")
        for field in (
            "longitudinal_estimator_admitted",
            "causal_estimation_admitted",
            "effect_application_admitted",
        ):
            if admission.get(field) is not False:
                errors.append(f"admission_{field}_must_be_false")

    boundary = contract.get("claim_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("claim_boundary_required")
    else:
        for field in (
            "diagnostic_weights_not_outcome_estimator",
            "diagnostic_pass_not_exchangeability_proof",
            "synthetic_diagnostics_not_empirical_evidence",
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
        "schema": "gwm.geospatial_kernel.longitudinal_causal_diagnostics_validation.v1",
        "valid": not errors,
        "errors": errors,
        **expected_readiness,
        "longitudinal_estimator_admitted": False,
        "causal_estimation_admitted": False,
        "effect_application_admitted": False,
        "general_geospatial_kernel_validated": False,
        "gwm_k0_validated": False,
    }


def seed_spatiotemporal_gate_evidence_from_longitudinal_diagnostics(
    diagnostic_contract: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Merge panel and diagnostic evidence without inventing estimator evidence."""

    validation = validate_longitudinal_causal_diagnostic_contract(
        diagnostic_contract
    )
    if not validation["valid"]:
        raise ValueError(
            "longitudinal_causal_diagnostic_contract_invalid:"
            + str(validation["errors"][0])
        )
    panel_contract = diagnostic_contract["panel_validation_contract"]
    evidence = seed_spatiotemporal_gate_evidence_from_panel_validation(
        panel_contract
    )
    digest = str(diagnostic_contract["contract_digest"])
    checks = diagnostic_contract["checks"]
    empirical_ready = validation["empirical_diagnostic_evidence_ready"]
    gate_checks = {
        "positivity_by_time_diagnosed": ("positivity_by_time_passed",),
        "censoring_and_missingness_diagnosed": (
            "censoring_diagnostic_passed",
        ),
        "sequential_balance_passed": ("sequential_balance_passed",),
        "weight_stability_passed": (
            "treatment_weight_stability_passed",
            "combined_weight_stability_passed",
        ),
    }
    for gate_name, required_checks in gate_checks.items():
        threshold_passed = all(
            checks[check_name]["passed"] is True
            for check_name in required_checks
        )
        passed = bool(empirical_ready and threshold_passed)
        if not empirical_ready:
            reason = "empirical_diagnostic_evidence_not_ready"
        elif not threshold_passed:
            reason = "diagnostic_threshold_failed"
        else:
            reason = "hash_bound_longitudinal_diagnostic_passed"
        refs = [
            f"longitudinal_causal_diagnostics:{digest}#{check_name}"
            for check_name in required_checks
        ]
        evidence[gate_name] = {
            "passed": passed,
            "evidence_refs": refs if empirical_ready else [],
            "details": {
                "reason": reason,
                "required_diagnostic_checks": list(required_checks),
                "empirical_diagnostic_evidence_ready": empirical_ready,
                "diagnostic_contract_digest": digest,
            },
        }
    return {
        gate_name: evidence[gate_name]
        for gate_name in (*LONGITUDINAL_DESIGN_GATES, *LONGITUDINAL_ESTIMATION_GATES)
    }


def _compute_diagnostics(
    *,
    panel_validation_contract: Mapping[str, Any],
    panel_rows: list[dict[str, Any]],
    diagnostic_rows: list[dict[str, Any]],
    field_mapping: Mapping[str, Any],
    analysis: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    panel_ref = "panel_rows_sha256:" + str(manifest["panel_rows_sha256"])
    diagnostic_ref = "diagnostic_rows_sha256:" + str(
        manifest["diagnostic_rows_sha256"]
    )
    contract_ref = "panel_validation_contract:" + str(
        panel_validation_contract.get("contract_digest")
    )
    refs = [panel_ref, diagnostic_ref, contract_ref]

    panel_manifest = panel_validation_contract.get("row_manifest")
    panel_manifest = panel_manifest if isinstance(panel_manifest, Mapping) else {}
    panel_hash_bound = bool(
        manifest["panel_rows_sha256"]
        == panel_manifest.get("panel_rows_sha256")
        and manifest["panel_row_count"]
        == panel_manifest.get("panel_row_count")
    )

    panel_mapping = panel_validation_contract.get("field_mapping")
    panel_mapping = panel_mapping if isinstance(panel_mapping, Mapping) else {}
    panel_unit_field = panel_mapping.get("unit_id_field")
    panel_time_field = panel_mapping.get("panel_time_field")
    diagnostic_unit_field = field_mapping.get("unit_id_field")
    diagnostic_time_field = field_mapping.get("time_field")
    panel_index = [
        _index_key(row.get(panel_unit_field), row.get(panel_time_field))
        for row in panel_rows
    ]
    diagnostic_index = [
        _index_key(
            row.get(diagnostic_unit_field), row.get(diagnostic_time_field)
        )
        for row in diagnostic_rows
    ]
    index_complete = bool(
        panel_hash_bound
        and len(panel_index) == len(set(panel_index))
        and len(diagnostic_index) == len(set(diagnostic_index))
        and set(panel_index) == set(diagnostic_index)
    )
    panel_by_index = {
        _index_key(row.get(panel_unit_field), row.get(panel_time_field)): row
        for row in panel_rows
    }
    diagnostic_by_index = {
        _index_key(
            row.get(diagnostic_unit_field), row.get(diagnostic_time_field)
        ): row
        for row in diagnostic_rows
    }
    joined = [
        (panel_by_index[key], diagnostic_by_index[key])
        for key in sorted(set(panel_by_index) & set(diagnostic_by_index))
    ]

    numeric_fields = (
        "propensity_score_field",
        "treatment_numerator_probability_field",
        "treatment_weight_field",
        "censoring_survival_probability_field",
        "censoring_numerator_probability_field",
        "censoring_weight_field",
    )
    finite_values = bool(index_complete and joined)
    for _, diagnostic in joined:
        values = {
            name: _finite_number(diagnostic.get(field_mapping.get(name)))
            for name in numeric_fields
        }
        if any(value is None for value in values.values()):
            finite_values = False
            break
        if not (
            0.0 < values["propensity_score_field"] < 1.0
            and 0.0
            < values["treatment_numerator_probability_field"]
            <= 1.0
            and values["treatment_weight_field"] > 0.0
            and 0.0
            < values["censoring_survival_probability_field"]
            <= 1.0
            and 0.0
            < values["censoring_numerator_probability_field"]
            <= 1.0
            and values["censoring_weight_field"] > 0.0
        ):
            finite_values = False
            break

    nuisance = analysis.get("nuisance_estimation")
    nuisance = nuisance if isinstance(nuisance, Mapping) else {}
    fold_field = field_mapping.get("cross_fit_fold_field")
    cutoff_field = field_mapping.get("nuisance_training_cutoff_field")
    folds_by_unit: dict[str, set[str]] = defaultdict(set)
    observed_folds: set[str] = set()
    nuisance_verified = bool(
        index_complete
        and nuisance.get("strategy")
        == "unit_grouped_forward_chaining_cross_fit"
        and nuisance.get("cross_fitted") is True
        and nuisance.get("unit_grouped") is True
        and nuisance.get("temporal_order_preserved") is True
    )
    for panel, diagnostic in joined:
        unit = str(panel.get(panel_unit_field))
        fold = diagnostic.get(fold_field)
        cutoff = _parse_timestamp(diagnostic.get(cutoff_field))
        panel_time = _parse_timestamp(panel.get(panel_time_field))
        if not _is_explicit(fold) or cutoff is None or panel_time is None:
            nuisance_verified = False
            continue
        folds_by_unit[unit].add(str(fold))
        observed_folds.add(str(fold))
        if cutoff >= panel_time:
            nuisance_verified = False
    declared_fold_count = nuisance.get("fold_count")
    if (
        any(len(folds) != 1 for folds in folds_by_unit.values())
        or isinstance(declared_fold_count, bool)
        or not isinstance(declared_fold_count, int)
        or len(observed_folds) != declared_fold_count
    ):
        nuisance_verified = False

    by_time: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(
        list
    )
    for panel, diagnostic in joined:
        by_time[str(panel.get(panel_time_field))].append((panel, diagnostic))

    treatment_field = panel_mapping.get("treatment_field")
    propensity_field = field_mapping.get("propensity_score_field")
    treatment_weight_field = field_mapping.get("treatment_weight_field")
    censoring_probability_field = field_mapping.get(
        "censoring_survival_probability_field"
    )
    censoring_weight_field = field_mapping.get("censoring_weight_field")
    treatment_numerator_field = field_mapping.get(
        "treatment_numerator_probability_field"
    )
    censoring_numerator_field = field_mapping.get(
        "censoring_numerator_probability_field"
    )
    censoring_field = panel_mapping.get("censoring_indicator_field")
    missingness_policy = panel_validation_contract.get("missingness_policy")
    missingness_policy = (
        missingness_policy if isinstance(missingness_policy, Mapping) else {}
    )
    censored_value = missingness_policy.get("censoring_value_when_missing")
    observed_censoring_value = analysis.get(
        "observed_censoring_indicator_value"
    )
    if any(
        panel.get(treatment_field) not in (0, 1, False, True)
        or panel.get(censoring_field)
        not in (censored_value, observed_censoring_value)
        for panel, _ in joined
    ):
        finite_values = False

    maximum_formula_error = _threshold_number(
        thresholds,
        "maximum_weight_formula_absolute_error",
        default=-1.0,
    )
    treatment_formula_errors = []
    censoring_formula_errors = []
    formula_consistent = bool(finite_values and joined)
    for panel, diagnostic in joined:
        treatment = panel.get(treatment_field)
        propensity = _finite_number(diagnostic.get(propensity_field))
        treatment_numerator = _finite_number(
            diagnostic.get(treatment_numerator_field)
        )
        treatment_weight = _finite_number(
            diagnostic.get(treatment_weight_field)
        )
        survival_probability = _finite_number(
            diagnostic.get(censoring_probability_field)
        )
        censoring_numerator = _finite_number(
            diagnostic.get(censoring_numerator_field)
        )
        censoring_weight = _finite_number(
            diagnostic.get(censoring_weight_field)
        )
        if None in (
            propensity,
            treatment_numerator,
            treatment_weight,
            survival_probability,
            censoring_numerator,
            censoring_weight,
        ):
            formula_consistent = False
            continue
        treatment_denominator = (
            propensity if treatment in (1, True) else 1.0 - propensity
        )
        censoring_denominator = (
            survival_probability
            if panel.get(censoring_field) == observed_censoring_value
            else 1.0 - survival_probability
        )
        if treatment_denominator <= 0.0 or censoring_denominator <= 0.0:
            formula_consistent = False
            continue
        treatment_error = abs(
            treatment_weight - treatment_numerator / treatment_denominator
        )
        censoring_error = abs(
            censoring_weight - censoring_numerator / censoring_denominator
        )
        treatment_formula_errors.append(treatment_error)
        censoring_formula_errors.append(censoring_error)
        if (
            treatment_error > maximum_formula_error
            or censoring_error > maximum_formula_error
        ):
            formula_consistent = False

    structural_checks = {
        "panel_rows_hash_bound": _check(
            panel_hash_bound,
            refs,
            {
                "expected_panel_rows_sha256": panel_manifest.get(
                    "panel_rows_sha256"
                ),
                "observed_panel_rows_sha256": manifest["panel_rows_sha256"],
            },
        ),
        "diagnostic_index_unique_complete": _check(
            index_complete,
            refs,
            {
                "panel_index_count": len(panel_index),
                "diagnostic_index_count": len(diagnostic_index),
                "joined_index_count": len(joined),
            },
        ),
        "diagnostic_values_finite": _check(
            finite_values,
            refs,
            {"required_numeric_fields": list(numeric_fields)},
        ),
        "nuisance_cross_fitting_verified": _check(
            nuisance_verified,
            refs,
            {
                "observed_fold_count": len(observed_folds),
                "declared_fold_count": declared_fold_count,
                "unit_count": len(folds_by_unit),
            },
        ),
        "weight_formula_consistency_verified": _check(
            formula_consistent,
            refs,
            {
                "formula": analysis.get("weight_formula"),
                "maximum_treatment_formula_absolute_error": _round(
                    max(treatment_formula_errors)
                    if treatment_formula_errors
                    else None
                ),
                "maximum_censoring_formula_absolute_error": _round(
                    max(censoring_formula_errors)
                    if censoring_formula_errors
                    else None
                ),
            },
        ),
    }
    if not index_complete or not finite_values:
        failed = {
            check_name: _check(
                False,
                refs,
                {"reason": "diagnostic_execution_inputs_invalid"},
            )
            for check_name in LONGITUDINAL_DIAGNOSTIC_THRESHOLD_CHECKS
        }
        return {**structural_checks, **failed}

    positivity_periods = []
    positivity_passed = bool(finite_values and by_time)
    for time_value in sorted(by_time):
        rows = by_time[time_value]
        propensities = [
            float(diagnostic[propensity_field]) for _, diagnostic in rows
        ]
        treated_count = sum(
            panel.get(treatment_field) in (1, True) for panel, _ in rows
        )
        control_count = len(rows) - treated_count
        period_passed = bool(
            treated_count >= thresholds.get("minimum_treated_per_time", math.inf)
            and control_count
            >= thresholds.get("minimum_control_per_time", math.inf)
            and min(propensities)
            >= thresholds.get("minimum_propensity", math.inf)
            and max(propensities)
            <= thresholds.get("maximum_propensity", -math.inf)
        )
        positivity_passed = positivity_passed and period_passed
        positivity_periods.append(
            {
                "time": time_value,
                "row_count": len(rows),
                "treated_count": treated_count,
                "control_count": control_count,
                "minimum_propensity": _round(min(propensities)),
                "maximum_propensity": _round(max(propensities)),
                "passed": period_passed,
            }
        )

    balance_fields = analysis.get("balance_confounder_fields")
    balance_fields = balance_fields if isinstance(balance_fields, list) else []
    balance_periods = []
    balance_passed = bool(finite_values and by_time and balance_fields)
    maximum_smd = 0.0
    for time_value in sorted(by_time):
        rows = by_time[time_value]
        for covariate in balance_fields:
            treated_values = []
            treated_weights = []
            control_values = []
            control_weights = []
            for panel, diagnostic in rows:
                value = _finite_number(panel.get(covariate))
                weight = _finite_number(diagnostic.get(treatment_weight_field))
                if value is None or weight is None:
                    continue
                if panel.get(treatment_field) in (1, True):
                    treated_values.append(value)
                    treated_weights.append(weight)
                else:
                    control_values.append(value)
                    control_weights.append(weight)
            smd = _weighted_standardized_mean_difference(
                treated_values,
                treated_weights,
                control_values,
                control_weights,
            )
            passed = bool(
                smd is not None
                and abs(smd)
                <= thresholds.get(
                    "maximum_absolute_standardized_mean_difference", -1.0
                )
            )
            balance_passed = balance_passed and passed
            if smd is not None:
                maximum_smd = max(maximum_smd, abs(smd))
            balance_periods.append(
                {
                    "time": time_value,
                    "covariate": covariate,
                    "standardized_mean_difference": _round(smd),
                    "passed": passed,
                }
            )

    treatment_weight_periods = []
    treatment_weights_passed = bool(finite_values and by_time)
    for time_value in sorted(by_time):
        weights = [
            float(diagnostic[treatment_weight_field])
            for _, diagnostic in by_time[time_value]
        ]
        summary = _weight_summary(weights)
        passed = _weight_summary_passed(
            summary,
            maximum=thresholds.get("maximum_treatment_weight"),
            maximum_cv=thresholds.get("maximum_treatment_weight_cv"),
            minimum_ess_fraction=thresholds.get(
                "minimum_treatment_effective_sample_size_fraction"
            ),
        )
        treatment_weights_passed = treatment_weights_passed and passed
        treatment_weight_periods.append(
            {"time": time_value, **summary, "passed": passed}
        )

    censoring_periods = []
    censoring_passed = bool(finite_values and by_time)
    for time_value in sorted(by_time):
        rows = by_time[time_value]
        probabilities = [
            float(diagnostic[censoring_probability_field])
            for _, diagnostic in rows
        ]
        weights = [
            float(diagnostic[censoring_weight_field])
            for _, diagnostic in rows
        ]
        censored_count = sum(
            panel.get(censoring_field) == censored_value for panel, _ in rows
        )
        censoring_rate = censored_count / len(rows)
        period_passed = bool(
            censoring_rate <= thresholds.get("maximum_censoring_rate", -1.0)
            and min(probabilities)
            >= thresholds.get(
                "minimum_censoring_survival_probability", math.inf
            )
            and max(weights) <= thresholds.get("maximum_censoring_weight", -1.0)
        )
        censoring_passed = censoring_passed and period_passed
        censoring_periods.append(
            {
                "time": time_value,
                "row_count": len(rows),
                "censored_count": censored_count,
                "censoring_rate": _round(censoring_rate),
                "minimum_survival_probability": _round(min(probabilities)),
                "maximum_censoring_weight": _round(max(weights)),
                "passed": period_passed,
            }
        )

    combined_weight_periods = []
    combined_weights_passed = bool(finite_values and by_time)
    for time_value in sorted(by_time):
        weights = [
            float(diagnostic[treatment_weight_field])
            * float(diagnostic[censoring_weight_field])
            for _, diagnostic in by_time[time_value]
        ]
        summary = _weight_summary(weights)
        passed = _weight_summary_passed(
            summary,
            maximum=thresholds.get("maximum_combined_weight"),
            maximum_cv=thresholds.get("maximum_combined_weight_cv"),
            minimum_ess_fraction=thresholds.get(
                "minimum_combined_effective_sample_size_fraction"
            ),
        )
        combined_weights_passed = combined_weights_passed and passed
        combined_weight_periods.append(
            {"time": time_value, **summary, "passed": passed}
        )

    return {
        **structural_checks,
        "positivity_by_time_passed": _check(
            positivity_passed,
            refs,
            {"periods": positivity_periods},
        ),
        "sequential_balance_passed": _check(
            balance_passed,
            refs,
            {
                "maximum_absolute_standardized_mean_difference": _round(
                    maximum_smd
                ),
                "period_covariates": balance_periods,
            },
        ),
        "treatment_weight_stability_passed": _check(
            treatment_weights_passed,
            refs,
            {"periods": treatment_weight_periods},
        ),
        "censoring_diagnostic_passed": _check(
            censoring_passed,
            refs,
            {"periods": censoring_periods},
        ),
        "combined_weight_stability_passed": _check(
            combined_weights_passed,
            refs,
            {"periods": combined_weight_periods},
        ),
    }


def _assess_readiness(
    *,
    panel_validation_contract: Mapping[str, Any],
    checks: Mapping[str, Any],
) -> dict[str, Any]:
    panel_validation = validate_longitudinal_panel_validation_contract(
        panel_validation_contract
    )
    blocking_execution = [
        name
        for name in LONGITUDINAL_DIAGNOSTIC_EXECUTION_CHECKS
        if not _check_passed(checks.get(name))
    ]
    blocking_thresholds = [
        name
        for name in LONGITUDINAL_DIAGNOSTIC_THRESHOLD_CHECKS
        if not _check_passed(checks.get(name))
    ]
    execution_ready = not blocking_execution
    empirical_ready = bool(
        panel_validation["valid"]
        and panel_validation["empirical_panel_evidence_ready"]
        and execution_ready
    )
    threshold_results = {
        "positivity_by_time_ready": bool(
            empirical_ready and _check_passed(checks.get("positivity_by_time_passed"))
        ),
        "sequential_balance_ready": bool(
            empirical_ready and _check_passed(checks.get("sequential_balance_passed"))
        ),
        "treatment_weight_stability_ready": bool(
            empirical_ready
            and _check_passed(checks.get("treatment_weight_stability_passed"))
        ),
        "censoring_diagnostic_ready": bool(
            empirical_ready
            and _check_passed(checks.get("censoring_diagnostic_passed"))
        ),
        "combined_weight_stability_ready": bool(
            empirical_ready
            and _check_passed(checks.get("combined_weight_stability_passed"))
        ),
    }
    return {
        "diagnostic_execution_ready": execution_ready,
        "empirical_diagnostic_evidence_ready": empirical_ready,
        **threshold_results,
        "all_diagnostic_thresholds_passed": bool(
            empirical_ready and not blocking_thresholds
        ),
        "blocking_execution_checks": blocking_execution,
        "blocking_threshold_checks": blocking_thresholds,
        "longitudinal_estimator_executed": False,
        "causal_identification_ready": False,
        "effect_application_admitted": False,
    }


def _validate_field_mapping(mapping: Mapping[str, Any], errors: list[str]) -> None:
    for field in (
        "unit_id_field",
        "time_field",
        "propensity_score_field",
        "treatment_weight_field",
        "censoring_survival_probability_field",
        "censoring_weight_field",
        "treatment_numerator_probability_field",
        "censoring_numerator_probability_field",
        "cross_fit_fold_field",
        "nuisance_training_cutoff_field",
    ):
        if not _is_nonempty_string(mapping.get(field)):
            errors.append(f"field_mapping_{field}_required")
    values = [mapping.get(field) for field in mapping]
    if len(values) != len(set(map(str, values))):
        errors.append("field_mapping_fields_must_be_distinct")


def _validate_analysis(
    analysis: Mapping[str, Any],
    panel_contract: Mapping[str, Any],
    errors: list[str],
) -> None:
    if analysis.get("weighting_estimand") not in _WEIGHTING_ESTIMANDS:
        errors.append("analysis_weighting_estimand_invalid")
    if analysis.get("risk_set") not in _RISK_SETS:
        errors.append("analysis_risk_set_invalid")
    if analysis.get("weight_formula") != (
        "stabilized_observed_action_and_status_probability_ratio"
    ):
        errors.append("analysis_weight_formula_invalid")
    observed_censoring_value = analysis.get(
        "observed_censoring_indicator_value"
    )
    missingness = panel_contract.get("missingness_policy")
    missingness = missingness if isinstance(missingness, Mapping) else {}
    if observed_censoring_value == missingness.get(
        "censoring_value_when_missing"
    ):
        errors.append("analysis_censoring_indicator_values_must_differ")
    if not _is_explicit(observed_censoring_value):
        errors.append("analysis_observed_censoring_indicator_value_required")
    fields = analysis.get("balance_confounder_fields")
    if not _is_string_list(fields):
        errors.append("analysis_balance_confounder_fields_must_be_string_list")
    panel_mapping = panel_contract.get("field_mapping")
    panel_mapping = panel_mapping if isinstance(panel_mapping, Mapping) else {}
    allowed_fields = set(panel_mapping.get("baseline_confounder_fields") or [])
    allowed_fields.update(panel_mapping.get("time_varying_confounder_fields") or [])
    if isinstance(fields, list) and not set(fields).issubset(allowed_fields):
        errors.append("analysis_balance_fields_not_in_panel_confounders")
    nuisance = analysis.get("nuisance_estimation")
    if not isinstance(nuisance, Mapping):
        errors.append("analysis_nuisance_estimation_required")
        return
    if nuisance.get("strategy") != "unit_grouped_forward_chaining_cross_fit":
        errors.append("analysis_nuisance_strategy_invalid")
    for field in ("cross_fitted", "unit_grouped", "temporal_order_preserved"):
        if not isinstance(nuisance.get(field), bool):
            errors.append(f"analysis_nuisance_{field}_must_be_boolean")
    fold_count = nuisance.get("fold_count")
    if (
        isinstance(fold_count, bool)
        or not isinstance(fold_count, int)
        or fold_count < 2
    ):
        errors.append("analysis_nuisance_fold_count_invalid")


def _validate_thresholds(
    thresholds: Mapping[str, Any], errors: list[str]
) -> None:
    minimum_propensity = _finite_number(thresholds.get("minimum_propensity"))
    maximum_propensity = _finite_number(thresholds.get("maximum_propensity"))
    if (
        minimum_propensity is None
        or maximum_propensity is None
        or not 0.0 < minimum_propensity < maximum_propensity < 1.0
    ):
        errors.append("thresholds_propensity_interval_invalid")
    for field in ("minimum_treated_per_time", "minimum_control_per_time"):
        value = thresholds.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            errors.append(f"thresholds_{field}_invalid")
    nonnegative_fields = (
        "maximum_absolute_standardized_mean_difference",
        "maximum_treatment_weight_cv",
        "maximum_combined_weight_cv",
        "maximum_censoring_rate",
        "maximum_weight_formula_absolute_error",
    )
    for field in nonnegative_fields:
        value = _finite_number(thresholds.get(field))
        if value is None or value < 0.0:
            errors.append(f"thresholds_{field}_invalid")
    positive_fields = (
        "maximum_treatment_weight",
        "maximum_censoring_weight",
        "maximum_combined_weight",
        "minimum_censoring_survival_probability",
    )
    for field in positive_fields:
        value = _finite_number(thresholds.get(field))
        if value is None or value <= 0.0:
            errors.append(f"thresholds_{field}_invalid")
    for field in (
        "minimum_treatment_effective_sample_size_fraction",
        "minimum_combined_effective_sample_size_fraction",
    ):
        value = _finite_number(thresholds.get(field))
        if value is None or not 0.0 < value <= 1.0:
            errors.append(f"thresholds_{field}_invalid")
    for field in (
        "maximum_censoring_rate",
        "minimum_censoring_survival_probability",
    ):
        value = _finite_number(thresholds.get(field))
        if value is not None and value > 1.0:
            errors.append(f"thresholds_{field}_above_one")


def _validate_provenance(provenance: Mapping[str, Any], errors: list[str]) -> None:
    for field in (
        "diagnostic_runner_version",
        "generated_at",
        "propensity_model_ref",
        "censoring_model_ref",
    ):
        if not _is_explicit(provenance.get(field)):
            errors.append(f"provenance_{field}_required")
    if _parse_timestamp(provenance.get("generated_at")) is None:
        errors.append("provenance_generated_at_invalid")
    for field in ("propensity_model_sha256", "censoring_model_sha256"):
        if not _is_sha256(provenance.get(field)):
            errors.append(f"provenance_{field}_invalid")


def _weighted_standardized_mean_difference(
    treated_values: list[float],
    treated_weights: list[float],
    control_values: list[float],
    control_weights: list[float],
) -> float | None:
    if not treated_values or not control_values:
        return None
    treated_mean = _weighted_mean(treated_values, treated_weights)
    control_mean = _weighted_mean(control_values, control_weights)
    treated_variance = _weighted_variance(
        treated_values, treated_weights, treated_mean
    )
    control_variance = _weighted_variance(
        control_values, control_weights, control_mean
    )
    pooled = math.sqrt(max(0.0, (treated_variance + control_variance) / 2.0))
    difference = treated_mean - control_mean
    if pooled == 0.0:
        return 0.0 if difference == 0.0 else None
    return difference / pooled


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    total_weight = sum(weights)
    return sum(value * weight for value, weight in zip(values, weights)) / total_weight


def _weighted_variance(
    values: list[float], weights: list[float], mean: float
) -> float:
    total_weight = sum(weights)
    return (
        sum(weight * (value - mean) ** 2 for value, weight in zip(values, weights))
        / total_weight
    )


def _weight_summary(weights: list[float]) -> dict[str, Any]:
    count = len(weights)
    mean = sum(weights) / count
    variance = sum((weight - mean) ** 2 for weight in weights) / count
    coefficient_of_variation = math.sqrt(variance) / mean
    effective_sample_size = sum(weights) ** 2 / sum(
        weight**2 for weight in weights
    )
    return {
        "count": count,
        "minimum": _round(min(weights)),
        "maximum": _round(max(weights)),
        "mean": _round(mean),
        "coefficient_of_variation": _round(coefficient_of_variation),
        "effective_sample_size": _round(effective_sample_size),
        "effective_sample_size_fraction": _round(effective_sample_size / count),
    }


def _weight_summary_passed(
    summary: Mapping[str, Any],
    *,
    maximum: Any,
    maximum_cv: Any,
    minimum_ess_fraction: Any,
) -> bool:
    return bool(
        _finite_number(maximum) is not None
        and _finite_number(maximum_cv) is not None
        and _finite_number(minimum_ess_fraction) is not None
        and summary["maximum"] <= float(maximum)
        and summary["coefficient_of_variation"] <= float(maximum_cv)
        and summary["effective_sample_size_fraction"]
        >= float(minimum_ess_fraction)
    )


def _threshold_number(
    thresholds: Mapping[str, Any], field: str, *, default: float
) -> float:
    value = _finite_number(thresholds.get(field))
    return default if value is None else value


def _check(
    passed: bool,
    evidence_refs: list[str],
    details: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "passed": bool(passed),
        "evidence_refs": list(evidence_refs),
        "details": deepcopy(dict(details)),
    }


def _check_passed(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("passed") is True
        and _is_string_list(value.get("evidence_refs"))
    )


def _normalize_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = [deepcopy(dict(row)) for row in rows]
    return sorted(normalized, key=_canonical_json)


def _index_key(unit_id: Any, time_value: Any) -> str:
    return _canonical_json([unit_id, time_value])


def _require_mapping(
    contract: Mapping[str, Any], field: str, errors: list[str]
) -> Mapping[str, Any]:
    value = contract.get(field)
    if not isinstance(value, Mapping):
        errors.append(f"{field}_required")
        return {}
    return value


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value):
        return None
    return round(value, 8)


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


def _is_string_list(value: Any) -> bool:
    return bool(
        isinstance(value, list)
        and value
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
