"""Deterministic replicate-level G0-G6 and truth-recovery assessment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.intervention_evidence_certificate import (
    CertificateEvaluation,
    GateStatus,
    evaluate_certificate,
)
from data_agent.uwm.regimeworld_iec_benchmark import (
    ModelVariant,
    semantic_prediction_gate,
)
from data_agent.uwm.regimeworld_iec_generator import ControlledScenarioSpec
from data_agent.uwm.regimeworld_iec_execution_guard import (
    ExternalEvaluationAuthorization,
)
from data_agent.uwm.regimeworld_iec_protocol import ProtocolThresholds


@dataclass(frozen=True)
class TruthRecoveryEvidence:
    response_relative_rmse: float | None
    jacobian_relative_frobenius_error: float | None
    jacobian_nonzero_sign_agreement: float | None


@dataclass(frozen=True)
class ReplicateEvidence:
    construct_frozen: bool
    feature_schema_allowlist_passed: bool
    oracle_access_count: int
    permutation_ledgers_frozen: bool
    development_metrics: Mapping[str, Mapping[str, object]] | None
    external_metrics: Mapping[str, Mapping[str, object]] | None
    external_authorization: ExternalEvaluationAuthorization | None
    token_response_max_abs: float | None
    truth_recovery: TruthRecoveryEvidence | None


@dataclass(frozen=True)
class ReplicateAssessment:
    gate_reasons: dict[str, str]
    certificate: CertificateEvaluation
    prediction_only_declaration: bool | None
    truth_recovery_pass: bool | None
    structurally_eligible: bool
    truth_positive: bool | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate_reasons": self.gate_reasons,
            "certificate": self.certificate.as_dict(),
            "prediction_only_declaration": self.prediction_only_declaration,
            "truth_recovery_pass": self.truth_recovery_pass,
            "structurally_eligible": self.structurally_eligible,
            "truth_positive": self.truth_positive,
        }


def _pairwise_prediction_improvement(
    metrics: Mapping[str, Mapping[str, object]],
    control_name: str,
) -> bool:
    primitive = metrics[ModelVariant.PRIMITIVE.value]
    control = metrics[control_name]
    if float(primitive["macro_nmae"]) >= float(control["macro_nmae"]):
        return False
    primitive_components = np.asarray(primitive["component_nmae"], dtype=np.float64)
    control_components = np.asarray(control["component_nmae"], dtype=np.float64)
    if primitive_components.shape != (4,) or control_components.shape != (4,):
        raise ValueError("prediction gate requires four component NMAEs")
    return int(np.count_nonzero(primitive_components < control_components)) >= 3


def prediction_only_declaration(
    external_metrics: Mapping[str, Mapping[str, object]] | None,
) -> bool | None:
    if external_metrics is None:
        return None
    return _pairwise_prediction_improvement(
        external_metrics,
        ModelVariant.NO_ACTION.value,
    )


def truth_recovery_decision(
    evidence: TruthRecoveryEvidence | None,
    *,
    thresholds: ProtocolThresholds,
) -> tuple[bool | None, bool | None]:
    """Return response and combined Jacobian decisions without imputing missing truth."""

    if evidence is None:
        return None, None
    response_pass = (
        None
        if evidence.response_relative_rmse is None
        else evidence.response_relative_rmse
        <= thresholds.relative_response_surface_rmse_max
    )
    if (
        evidence.jacobian_relative_frobenius_error is None
        or evidence.jacobian_nonzero_sign_agreement is None
    ):
        jacobian_pass = None
    else:
        jacobian_pass = (
            evidence.jacobian_relative_frobenius_error
            <= thresholds.relative_jacobian_frobenius_error_max
            and evidence.jacobian_nonzero_sign_agreement
            >= thresholds.nonzero_jacobian_sign_agreement_min
        )
    return response_pass, jacobian_pass


def structural_eligibility(spec: ControlledScenarioSpec) -> bool:
    return (
        spec.action_geometry == "independent"
        and spec.target_support == "interpolation"
        and spec.implementation_mode == "exact"
        and spec.contamination_mode == "absent"
        and spec.response_invariance == "shared"
    )


def assess_replicate(
    spec: ControlledScenarioSpec,
    evidence: ReplicateEvidence,
    *,
    thresholds: ProtocolThresholds | None = None,
) -> ReplicateAssessment:
    thresholds = thresholds or ProtocolThresholds()
    thresholds.validate()
    gates: dict[str, GateStatus] = {}
    reasons: dict[str, str] = {}

    gates["G0"] = GateStatus.PASS if evidence.construct_frozen else GateStatus.FAIL
    reasons["G0"] = "frozen_construct" if evidence.construct_frozen else "construct_not_frozen"

    if spec.implementation_mode == "exact":
        gates["G1"] = GateStatus.PASS
        reasons["G1"] = "exact_implementation"
    else:
        gates["G1"] = GateStatus.INDETERMINATE
        reasons["G1"] = "implemented_action_withheld_from_candidate"

    if spec.contamination_mode == "absent":
        gates["G2"] = GateStatus.PASS
        reasons["G2"] = "contamination_absent"
    else:
        gates["G2"] = GateStatus.FAIL
        reasons["G2"] = "auditor_truth_contains_latent_contamination"

    if spec.action_geometry != "independent":
        gates["G3"] = GateStatus.FAIL
        reasons["G3"] = "bundled_actions_do_not_excitate_primitive_components"
    elif spec.target_support != "interpolation":
        gates["G3"] = GateStatus.FAIL
        reasons["G3"] = "target_requires_extrapolation"
    else:
        gates["G3"] = GateStatus.PASS
        reasons["G3"] = "independent_actions_with_interpolation_support"

    if not evidence.feature_schema_allowlist_passed:
        gates["G4"] = GateStatus.FAIL
        reasons["G4"] = "candidate_feature_schema_violation"
    elif evidence.oracle_access_count != 0:
        gates["G4"] = GateStatus.FAIL
        reasons["G4"] = "candidate_or_selection_or_scaler_accessed_oracle_fields"
    elif not evidence.permutation_ledgers_frozen:
        gates["G4"] = GateStatus.FAIL
        reasons["G4"] = "permutation_ledgers_not_frozen"
    elif evidence.development_metrics is None:
        gates["G4"] = GateStatus.INDETERMINATE
        reasons["G4"] = "development_shortcut_control_not_evaluated"
    elif not all(
        _pairwise_prediction_improvement(evidence.development_metrics, control.value)
        for control in (
            ModelVariant.OPAQUE_TOKEN,
            ModelVariant.COMPONENT_SHUFFLED,
            ModelVariant.ACTION_PERMUTED,
        )
    ):
        gates["G4"] = GateStatus.FAIL
        reasons["G4"] = "shortcut_or_permutation_control_matches_or_beats_primitive"
    else:
        gates["G4"] = GateStatus.PASS
        reasons["G4"] = "allowlist_oracle_isolation_and_shortcut_permutation_controls_pass"

    if evidence.development_metrics is None:
        gates["G5"] = GateStatus.INDETERMINATE
        reasons["G5"] = "development_semantic_controls_not_evaluated"
    elif semantic_prediction_gate(evidence.development_metrics):
        gates["G5"] = GateStatus.PASS
        reasons["G5"] = "primitive_beats_all_matched_semantic_controls"
    else:
        gates["G5"] = GateStatus.FAIL
        reasons["G5"] = "incremental_or_semantic_specificity_failed"

    external_seal_valid = (
        evidence.external_authorization is not None
        and evidence.external_authorization.scenario_name == spec.name
        and bool(evidence.external_authorization.frozen_model_hashes)
        and set(evidence.external_authorization.frozen_model_hashes)
        == set(evidence.external_authorization.frozen_scaler_hashes)
        and (
            not evidence.external_authorization.scientific_result
            or evidence.external_authorization.reservation is not None
        )
    )
    if not external_seal_valid:
        gates["G6"] = GateStatus.INDETERMINATE
        reasons["G6"] = "external_evaluation_not_validly_unsealed"
    elif evidence.external_metrics is None:
        gates["G6"] = GateStatus.INDETERMINATE
        reasons["G6"] = "external_metrics_missing"
    elif spec.response_invariance != "shared":
        gates["G6"] = GateStatus.FAIL
        reasons["G6"] = "shared_response_transfer_is_false_by_scenario_truth"
    elif semantic_prediction_gate(evidence.external_metrics):
        gates["G6"] = GateStatus.PASS
        reasons["G6"] = "sealed_external_semantic_prediction_pass"
    else:
        gates["G6"] = GateStatus.FAIL
        reasons["G6"] = "sealed_external_semantic_prediction_failed"

    response_pass, jacobian_pass = truth_recovery_decision(
        evidence.truth_recovery,
        thresholds=thresholds,
    )
    token_responsive = (
        None
        if evidence.token_response_max_abs is None
        else evidence.token_response_max_abs > thresholds.action_support_tolerance
    )
    certificate = evaluate_certificate(
        gates,
        token_responsive=token_responsive,
        controlled_truth={
            "reference_available": evidence.truth_recovery is not None,
            "response_surface_pass": response_pass,
            "jacobian_pass": jacobian_pass,
        },
    )
    truth_pass = (
        response_pass and jacobian_pass
        if response_pass is not None and jacobian_pass is not None
        else None
    )
    eligible = structural_eligibility(spec)
    return ReplicateAssessment(
        gate_reasons=reasons,
        certificate=certificate,
        prediction_only_declaration=prediction_only_declaration(
            evidence.external_metrics
        ),
        truth_recovery_pass=truth_pass,
        structurally_eligible=eligible,
        truth_positive=(eligible and truth_pass) if truth_pass is not None else None,
    )
