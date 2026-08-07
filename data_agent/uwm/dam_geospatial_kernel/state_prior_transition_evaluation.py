"""Paired holdout evaluation for DAM-GK state-prior context."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import numpy as np
import torch

from .state_prior_context_adapter import (
    DAMGKStatePriorContextBinding,
    verify_dam_gk_state_prior_context_binding,
)
from .state_prior_transition_protocol import (
    REQUIRED_TRANSITION_HOLDOUT_SPLITS,
    TRANSITION_EVALUATION_METHODS,
    TRANSITION_PROTOCOL_PERMITTED_CLAIM,
    validate_dam_gk_state_prior_transition_protocol,
)
from .state_prior_transition_receipts import (
    validate_state_prior_transition_holdout_opening,
    validate_state_prior_transition_protocol_registration,
)

DAM_GK_STATE_PRIOR_TRANSITION_EVALUATION_SCHEMA = (
    "gwm.geospatial_kernel.state_prior_transition_evaluation.v1"
)

TRANSITION_EVALUATION_GATES = (
    "bindings_verified",
    "prediction_artifacts_verified",
    "observed_holdout_evidence_present",
    "required_holdout_splits_present",
    "minimum_sample_support_passed",
    "strict_leakage_audit_passed",
    "paired_action_forcing_topology_complete",
    "action_conditioned_support_passed",
    "full_beats_traditional_baseline_every_split",
    "full_beats_zero_prior_every_split",
    "full_beats_shuffled_prior_every_split",
    "calibrated_interval_coverage_every_split",
)

_PREDICTION_FIELDS = {
    "full_state_prior": "full_prediction",
    "zero_state_prior": "zero_prediction",
    "shuffled_state_prior": "shuffled_prediction",
    "traditional_baseline": "baseline_prediction",
}
_PREDICTION_ARTIFACT_FIELDS = {
    "uri",
    "created_at",
    "protocol_sha256",
    "protocol_registration_receipt_sha256",
    "holdout_opening_receipt_sha256",
    "holdout_manifest_sha256",
    "paired_input_sha256",
    "predictions_sha256",
    "model_sha256",
    "context_values_sha256",
}
_SUPPORTED_CLAIM = TRANSITION_PROTOCOL_PERMITTED_CLAIM
_NO_CLAIM = "no_state_prior_transition_skill_improvement_claim_supported"
_EXECUTION_CLAIM = "state_prior_transition_evaluator_execution_only"


def build_dam_gk_state_prior_transition_evaluation(
    *,
    evaluation_id: str,
    created_at: str,
    protocol: Mapping[str, Any],
    protocol_registration_receipt: Mapping[str, Any],
    holdout_opening_receipt: Mapping[str, Any],
    full_binding: DAMGKStatePriorContextBinding,
    zero_binding: DAMGKStatePriorContextBinding,
    shuffled_binding: DAMGKStatePriorContextBinding,
    holdout_records: Sequence[Mapping[str, Any]],
    prediction_artifacts: Mapping[str, Mapping[str, Any]],
    evidence_refs: Sequence[str],
    leakage_audit: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate representation gain under one hash-bound preregistration."""

    if not str(evaluation_id).strip():
        raise ValueError("state_prior_transition_evaluation_id_required")
    evaluation_created = _parse_aware_timestamp(created_at)
    if evaluation_created is None:
        raise ValueError("state_prior_transition_created_at_invalid")
    if not isinstance(protocol, Mapping):
        raise ValueError("state_prior_transition_protocol_required")
    protocol_payload = copy.deepcopy(dict(protocol))
    protocol_validation = validate_dam_gk_state_prior_transition_protocol(protocol_payload)
    if not protocol_validation["valid"]:
        raise ValueError(
            "invalid_state_prior_transition_protocol:" + ";".join(protocol_validation["errors"])
        )
    if not isinstance(protocol_registration_receipt, Mapping):
        raise ValueError("state_prior_transition_protocol_registration_receipt_required")
    registration_payload = copy.deepcopy(dict(protocol_registration_receipt))
    registration_validation = validate_state_prior_transition_protocol_registration(
        registration_payload,
        protocol=protocol_payload,
    )
    if not registration_validation["valid"]:
        raise ValueError(
            "invalid_state_prior_transition_protocol_registration:"
            + ";".join(registration_validation["errors"])
        )
    if not isinstance(holdout_opening_receipt, Mapping):
        raise ValueError("state_prior_transition_holdout_opening_receipt_required")
    opening_payload = copy.deepcopy(dict(holdout_opening_receipt))
    opening_validation = validate_state_prior_transition_holdout_opening(
        opening_payload,
        protocol=protocol_payload,
        registration_receipt=registration_payload,
    )
    if not opening_validation["valid"]:
        raise ValueError(
            "invalid_state_prior_transition_holdout_opening:"
            + ";".join(opening_validation["errors"])
        )
    holdout_accessed = _parse_aware_timestamp(opening_payload["opened_at"])
    if holdout_accessed is None:
        raise ValueError("state_prior_transition_holdout_accessed_at_invalid")
    if evaluation_created < holdout_accessed:
        raise ValueError("state_prior_transition_evaluation_before_holdout_access")
    source_evidence_kind = protocol_payload["source_evidence_kind"]
    design = protocol_payload["evaluation_design"]
    minimum_samples_per_split = design["minimum_samples_per_split"]
    minimum_relative_improvement = design["minimum_relative_improvement"]

    _verify_paired_bindings(full_binding, zero_binding, shuffled_binding)
    _verify_protocol_matches_bindings(
        protocol_payload,
        full=full_binding,
        zero=zero_binding,
        shuffled=shuffled_binding,
    )
    rows = _normalize_holdout_records(holdout_records)
    if any(row["node_key"] not in full_binding.node_keys for row in rows):
        raise ValueError("state_prior_transition_holdout_node_not_in_binding")
    normalized_evidence = _unique_nonempty_strings(evidence_refs, "evidence_refs")
    paired_input_sha256 = compute_state_prior_paired_input_sha256(rows)
    normalized_artifacts = _verify_prediction_artifacts(
        prediction_artifacts,
        rows=rows,
        paired_input_sha256=paired_input_sha256,
        bindings={
            "full_state_prior": full_binding,
            "zero_state_prior": zero_binding,
            "shuffled_state_prior": shuffled_binding,
        },
        evidence_refs=normalized_evidence,
        protocol=protocol_payload,
        registration_receipt=registration_payload,
        opening_receipt=opening_payload,
        evaluation_created=evaluation_created,
    )
    split_metrics = {
        split: _score_split([row for row in rows if row["split"] == split])
        for split in REQUIRED_TRANSITION_HOLDOUT_SPLITS
    }
    confidence_level = _binding_confidence_level(full_binding)
    if not math.isclose(
        confidence_level,
        float(design["confidence_level"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("state_prior_transition_protocol_confidence_mismatch")
    coverage_threshold = design["minimum_coverage_threshold"]
    sample_counts = {
        split: split_metrics[split]["sample_count"] for split in REQUIRED_TRANSITION_HOLDOUT_SPLITS
    }
    paired_context_complete = _paired_context_complete(rows, evidence_refs=set(normalized_evidence))
    strict_leakage = _strict_leakage_audit_passes(
        leakage_audit,
        protocol_rules=protocol_payload["split_specific_leakage_rules"],
    )
    action_support = _action_support_passes(rows)

    gates = {
        "bindings_verified": True,
        "prediction_artifacts_verified": True,
        "observed_holdout_evidence_present": (
            source_evidence_kind == "observed_holdout" and bool(normalized_evidence)
        ),
        "required_holdout_splits_present": all(
            sample_counts[split] > 0 for split in REQUIRED_TRANSITION_HOLDOUT_SPLITS
        ),
        "minimum_sample_support_passed": all(
            sample_counts[split] >= minimum_samples_per_split
            for split in REQUIRED_TRANSITION_HOLDOUT_SPLITS
        ),
        "strict_leakage_audit_passed": strict_leakage,
        "paired_action_forcing_topology_complete": paired_context_complete,
        "action_conditioned_support_passed": action_support,
        "full_beats_traditional_baseline_every_split": _beats_every_split(
            split_metrics,
            comparator="traditional_baseline",
            minimum_relative_improvement=minimum_relative_improvement,
        ),
        "full_beats_zero_prior_every_split": _beats_every_split(
            split_metrics,
            comparator="zero_state_prior",
            minimum_relative_improvement=minimum_relative_improvement,
        ),
        "full_beats_shuffled_prior_every_split": _beats_every_split(
            split_metrics,
            comparator="shuffled_state_prior",
            minimum_relative_improvement=minimum_relative_improvement,
        ),
        "calibrated_interval_coverage_every_split": all(
            split_metrics[split]["full_state_prior"]["interval_coverage"] >= coverage_threshold
            for split in REQUIRED_TRANSITION_HOLDOUT_SPLITS
            if sample_counts[split] > 0
        )
        and all(sample_counts.values()),
    }
    ready = all(gates.values())
    if ready:
        supported_claim = _SUPPORTED_CLAIM
        max_claim_level = "bounded_support"
    elif source_evidence_kind != "observed_holdout":
        supported_claim = _EXECUTION_CLAIM
        max_claim_level = "exploratory_only"
    else:
        supported_claim = _NO_CLAIM
        max_claim_level = "not_for_claim"

    result = {
        "schema": DAM_GK_STATE_PRIOR_TRANSITION_EVALUATION_SCHEMA,
        "version": "0.1",
        "evaluation_id": str(evaluation_id),
        "created_at": str(created_at),
        "source_evidence_kind": source_evidence_kind,
        "evidence_refs": list(normalized_evidence),
        "protocol_sha256": protocol_payload["protocol_sha256"],
        "transition_protocol": protocol_payload,
        "protocol_registration_receipt_sha256": registration_payload["registration_receipt_sha256"],
        "protocol_registration_receipt": registration_payload,
        "holdout_opening_receipt_sha256": opening_payload["holdout_opening_receipt_sha256"],
        "holdout_opening_receipt": opening_payload,
        "holdout_accessed_at": opening_payload["opened_at"],
        "holdout_manifest_sha256": opening_payload["holdout_manifest_sha256"],
        "state_prior_admission_id": full_binding.admission_id,
        "state_prior_id": full_binding.state_prior_id,
        "binding_receipts": {
            "full_state_prior": full_binding.as_dict(),
            "zero_state_prior": zero_binding.as_dict(),
            "shuffled_state_prior": shuffled_binding.as_dict(),
        },
        "prediction_artifacts": normalized_artifacts,
        "paired_input_sha256": paired_input_sha256,
        "holdout_protocol": copy.deepcopy(design),
        "leakage_audit": dict(leakage_audit),
        "holdout_record_count": len(rows),
        "sample_counts": sample_counts,
        "split_metrics": split_metrics,
        "readiness_gates": gates,
        "remaining_gates": [name for name in TRANSITION_EVALUATION_GATES if not gates[name]],
        "state_prior_transition_evaluation_ready": ready,
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": max_claim_level,
            "scope": "paired_state_prior_context_transition_skill_only",
        },
        "state_prior_transition_skill_improvement_claim": ready,
        "policy_causal_effect_claim": False,
        "action_conditioned_dynamics_claim": False,
        "general_geospatial_world_model_validation_claim": False,
        "autonomous_planning_superiority_claim": False,
        "limitations": [
            "predictive_skill_does_not_identify_policy_causal_effect",
            "state_prior_context_gain_does_not_validate_general_dynamics",
            "all_methods_must_use_identical_action_forcing_topology_and_holdout_cases",
        ],
    }
    validation = validate_dam_gk_state_prior_transition_evaluation(result)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_transition_evaluation:" + ";".join(validation["errors"])
        )
    return result


def validate_dam_gk_state_prior_transition_evaluation(
    payload: Any,
) -> dict[str, Any]:
    """Validate readiness consistency and prohibit claim escalation."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["evaluation_must_be_a_dictionary"]}
    errors: list[str] = []
    if payload.get("schema") != DAM_GK_STATE_PRIOR_TRANSITION_EVALUATION_SCHEMA:
        errors.append("evaluation_schema_mismatch")
    for field in ("evaluation_id", "created_at", "state_prior_admission_id", "state_prior_id"):
        if not _nonempty_string(payload.get(field)):
            errors.append(f"{field}_required")
    if not _valid_sha256(payload.get("paired_input_sha256")):
        errors.append("paired_input_sha256_invalid")

    protocol = payload.get("transition_protocol")
    protocol_values: dict[str, Any] = {}
    if not isinstance(protocol, dict):
        errors.append("transition_protocol_required")
    else:
        protocol_values = protocol
        protocol_validation = validate_dam_gk_state_prior_transition_protocol(protocol)
        errors.extend(f"transition_protocol_{error}" for error in protocol_validation["errors"])
        protocol_sha256 = protocol.get("protocol_sha256")
        if payload.get("protocol_sha256") != protocol_sha256:
            errors.append("transition_evaluation_protocol_sha256_mismatch")
        if payload.get("source_evidence_kind") != protocol.get("source_evidence_kind"):
            errors.append("transition_evaluation_source_evidence_kind_mismatch")
        if payload.get("holdout_protocol") != protocol.get("evaluation_design"):
            errors.append("transition_evaluation_holdout_protocol_mismatch")
        binding_contract = protocol.get("binding_contract")
        if isinstance(binding_contract, Mapping):
            if payload.get("state_prior_admission_id") != binding_contract.get(
                "state_prior_admission_id"
            ):
                errors.append("transition_evaluation_admission_id_mismatch")
            if payload.get("state_prior_id") != binding_contract.get("state_prior_id"):
                errors.append("transition_evaluation_state_prior_id_mismatch")

    registration = payload.get("protocol_registration_receipt")
    registration_values: dict[str, Any] = {}
    if not isinstance(registration, dict):
        errors.append("transition_evaluation_protocol_registration_receipt_required")
    else:
        registration_values = registration
        if protocol_values:
            registration_validation = validate_state_prior_transition_protocol_registration(
                registration,
                protocol=protocol_values,
            )
            errors.extend(
                f"transition_registration_{error}" for error in registration_validation["errors"]
            )
        if payload.get("protocol_registration_receipt_sha256") != registration.get(
            "registration_receipt_sha256"
        ):
            errors.append("transition_evaluation_registration_receipt_sha256_mismatch")

    opening = payload.get("holdout_opening_receipt")
    opening_values: dict[str, Any] = {}
    if not isinstance(opening, dict):
        errors.append("transition_evaluation_holdout_opening_receipt_required")
    else:
        opening_values = opening
        if protocol_values and registration_values:
            opening_validation = validate_state_prior_transition_holdout_opening(
                opening,
                protocol=protocol_values,
                registration_receipt=registration_values,
            )
            errors.extend(f"transition_opening_{error}" for error in opening_validation["errors"])
        if payload.get("holdout_opening_receipt_sha256") != opening.get(
            "holdout_opening_receipt_sha256"
        ):
            errors.append("transition_evaluation_holdout_opening_receipt_sha256_mismatch")
        if payload.get("holdout_accessed_at") != opening.get("opened_at"):
            errors.append("transition_evaluation_holdout_accessed_at_mismatch")
        if payload.get("holdout_manifest_sha256") != opening.get("holdout_manifest_sha256"):
            errors.append("transition_evaluation_holdout_manifest_sha256_mismatch")

    created = _parse_aware_timestamp(payload.get("created_at"))
    holdout_accessed = _parse_aware_timestamp(
        opening_values.get("opened_at") if opening_values else None
    )
    if created is None:
        errors.append("transition_evaluation_created_at_invalid")
    if holdout_accessed is None:
        errors.append("transition_evaluation_holdout_accessed_at_invalid")
    if created is not None and holdout_accessed is not None and created < holdout_accessed:
        errors.append("transition_evaluation_created_before_holdout_access")

    artifacts = payload.get("prediction_artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(TRANSITION_EVALUATION_METHODS):
        errors.append("transition_evaluation_prediction_artifact_set_mismatch")
    elif protocol_values:
        protocol_sha256 = protocol_values.get("protocol_sha256")
        model_contract = protocol_values.get("model_contract")
        candidate_model = (
            model_contract.get("candidate_control_shared_model_sha256")
            if isinstance(model_contract, Mapping)
            else None
        )
        baseline_model = (
            model_contract.get("traditional_baseline_model_sha256")
            if isinstance(model_contract, Mapping)
            else None
        )
        registration_sha256 = registration_values.get("registration_receipt_sha256")
        opening_sha256 = opening_values.get("holdout_opening_receipt_sha256")
        holdout_manifest_sha256 = opening_values.get("holdout_manifest_sha256")
        for method in TRANSITION_EVALUATION_METHODS:
            artifact = artifacts.get(method)
            if not isinstance(artifact, Mapping):
                errors.append(f"transition_evaluation_{method}_artifact_invalid")
                continue
            if set(artifact) != _PREDICTION_ARTIFACT_FIELDS:
                errors.append(f"transition_evaluation_{method}_artifact_field_set_mismatch")
            if artifact.get("protocol_sha256") != protocol_sha256:
                errors.append(f"transition_evaluation_{method}_protocol_sha256_mismatch")
            if artifact.get("protocol_registration_receipt_sha256") != registration_sha256:
                errors.append(f"transition_evaluation_{method}_registration_sha256_mismatch")
            if artifact.get("holdout_opening_receipt_sha256") != opening_sha256:
                errors.append(f"transition_evaluation_{method}_opening_sha256_mismatch")
            if artifact.get("holdout_manifest_sha256") != holdout_manifest_sha256:
                errors.append(f"transition_evaluation_{method}_holdout_manifest_sha256_mismatch")
            artifact_created = _parse_aware_timestamp(artifact.get("created_at"))
            if artifact_created is None:
                errors.append(f"transition_evaluation_{method}_created_at_invalid")
            elif holdout_accessed is not None and artifact_created < holdout_accessed:
                errors.append(f"transition_evaluation_{method}_created_before_holdout_opening")
            elif created is not None and artifact_created > created:
                errors.append(f"transition_evaluation_{method}_created_after_evaluation")
            expected_model = baseline_model if method == "traditional_baseline" else candidate_model
            if artifact.get("model_sha256") != expected_model:
                errors.append(f"transition_evaluation_{method}_model_sha256_mismatch")
    gates = payload.get("readiness_gates")
    if not isinstance(gates, dict) or set(gates) != set(TRANSITION_EVALUATION_GATES):
        errors.append("transition_evaluation_gate_set_mismatch")
        gate_values: dict[str, Any] = {}
    else:
        gate_values = gates
        if any(not isinstance(value, bool) for value in gates.values()):
            errors.append("transition_evaluation_gate_values_must_be_boolean")
    evidence_refs = payload.get("evidence_refs")
    evidence_present = bool(
        isinstance(evidence_refs, list)
        and evidence_refs
        and all(_nonempty_string(value) for value in evidence_refs)
        and len(evidence_refs) == len(set(evidence_refs))
    )
    if not evidence_present:
        errors.append("transition_evaluation_evidence_refs_invalid")
    expected_observed_gate = (
        payload.get("source_evidence_kind") == "observed_holdout" and evidence_present
    )
    if (
        gate_values
        and gate_values.get("observed_holdout_evidence_present") != expected_observed_gate
    ):
        errors.append("transition_evaluation_observed_holdout_gate_inconsistent")
    ready = payload.get("state_prior_transition_evaluation_ready") is True
    all_gates_pass = bool(gate_values) and all(
        gate_values.get(name) is True for name in TRANSITION_EVALUATION_GATES
    )
    if ready != all_gates_pass:
        errors.append("transition_evaluation_readiness_must_equal_all_gates")
    expected_remaining = [
        name for name in TRANSITION_EVALUATION_GATES if gate_values.get(name) is not True
    ]
    if payload.get("remaining_gates") != expected_remaining:
        errors.append("transition_evaluation_remaining_gates_inconsistent")

    if ready:
        if payload.get("supported_claim") != _SUPPORTED_CLAIM:
            errors.append("ready_transition_evaluation_supported_claim_mismatch")
        if _claim_level(payload) != "bounded_support":
            errors.append("ready_transition_evaluation_requires_bounded_support")
        if payload.get("state_prior_transition_skill_improvement_claim") is not True:
            errors.append("ready_transition_skill_claim_required")
    else:
        if payload.get("supported_claim") == _SUPPORTED_CLAIM:
            errors.append("nonready_transition_evaluation_cannot_use_supported_claim")
        if _claim_level(payload) == "bounded_support":
            errors.append("nonready_transition_evaluation_cannot_use_bounded_support")
        if payload.get("state_prior_transition_skill_improvement_claim") is not False:
            errors.append("nonready_transition_skill_claim_must_be_false")
    for field in (
        "policy_causal_effect_claim",
        "action_conditioned_dynamics_claim",
        "general_geospatial_world_model_validation_claim",
        "autonomous_planning_superiority_claim",
    ):
        if payload.get(field) is not False:
            errors.append(f"{field}_must_be_false")
    return {"valid": not errors, "errors": errors}


def compute_state_prior_paired_input_sha256(
    holdout_records: Sequence[Mapping[str, Any]],
) -> str:
    """Hash paired case identity, observed target and fixed kernel inputs."""

    rows = _normalize_holdout_records(holdout_records)
    payload = [
        {
            key: row[key]
            for key in (
                "sample_id",
                "split",
                "node_key",
                "action_id",
                "target",
                "target_evidence_ref",
                "action_evidence_ref",
                "action_sha256",
                "forcing_sha256",
                "topology_sha256",
            )
        }
        for row in sorted(rows, key=lambda value: (value["split"], value["sample_id"]))
    ]
    return _json_sha256(payload)


def compute_state_prior_prediction_sha256(
    holdout_records: Sequence[Mapping[str, Any]], method: str
) -> str:
    """Hash one method's paired predictions using stable sample identity."""

    if method not in _PREDICTION_FIELDS:
        raise ValueError("state_prior_transition_prediction_method_invalid")
    rows = _normalize_holdout_records(holdout_records)
    field = _PREDICTION_FIELDS[method]
    payload = [
        {
            "sample_id": row["sample_id"],
            "split": row["split"],
            "prediction": row[field],
            **(
                {
                    "interval_lower": row["full_interval_lower"],
                    "interval_upper": row["full_interval_upper"],
                }
                if method == "full_state_prior"
                else {}
            ),
        }
        for row in sorted(rows, key=lambda value: (value["split"], value["sample_id"]))
    ]
    return _json_sha256(payload)


def _verify_paired_bindings(
    full: DAMGKStatePriorContextBinding,
    zero: DAMGKStatePriorContextBinding,
    shuffled: DAMGKStatePriorContextBinding,
) -> None:
    for binding in (full, zero, shuffled):
        verify_dam_gk_state_prior_context_binding(binding)
    if full.negative_control is not None:
        raise ValueError("state_prior_transition_full_binding_must_not_be_control")
    if zero.negative_control != "zero":
        raise ValueError("state_prior_transition_zero_binding_required")
    if shuffled.negative_control != "shuffle_nodes":
        raise ValueError("state_prior_transition_shuffled_binding_required")
    shared_fields = (
        "config",
        "node_keys",
        "context_feature_names",
        "state_prior_feature_names",
        "state_prior_feature_indices",
        "admission_id",
        "admission_sha256",
        "state_prior_id",
        "context_ref",
        "context_artifact_sha256",
        "fixed_kernel_inputs_sha256",
        "evidence_refs",
        "calibration_evidence_refs",
    )
    for control in (zero, shuffled):
        if any(getattr(control, field) != getattr(full, field) for field in shared_fields):
            raise ValueError("state_prior_transition_binding_metadata_mismatch")
        _verify_fixed_batch_inputs(full, control)

    indices = torch.tensor(full.state_prior_feature_indices, dtype=torch.long)
    full_values = full.batch.node_context[:, indices]
    zero_values = zero.batch.node_context[:, indices]
    shuffled_values = shuffled.batch.node_context[:, indices]
    if torch.count_nonzero(zero_values).item() != 0:
        raise ValueError("state_prior_transition_zero_control_not_zero")
    if torch.equal(full_values, shuffled_values):
        raise ValueError("state_prior_transition_shuffle_control_ineffective")
    if not torch.equal(
        torch.sort(full_values, dim=0).values,
        torch.sort(shuffled_values, dim=0).values,
    ):
        raise ValueError("state_prior_transition_shuffle_control_not_permutation")


def _verify_fixed_batch_inputs(
    full: DAMGKStatePriorContextBinding,
    control: DAMGKStatePriorContextBinding,
) -> None:
    prior_count = len(full.state_prior_feature_names)
    base_dim = full.config.context_dim - prior_count
    tensor_fields = (
        "node_state",
        "node_action",
        "edge_index",
        "edge_features",
        "edge_types",
        "teacher_state_by_step",
        "region_context",
        "edge_valid_mask",
    )
    for field in tensor_fields:
        if not _optional_tensor_equal(getattr(full.batch, field), getattr(control.batch, field)):
            raise ValueError(f"state_prior_transition_control_changed_{field}")
    if not torch.equal(
        full.batch.node_context[:, :base_dim], control.batch.node_context[:, :base_dim]
    ):
        raise ValueError("state_prior_transition_control_changed_base_context")
    if full.batch.node_context_by_step is not None and not torch.equal(
        full.batch.node_context_by_step[:, :, :base_dim],
        control.batch.node_context_by_step[:, :, :base_dim],
    ):
        raise ValueError("state_prior_transition_control_changed_step_context")


def _verify_protocol_matches_bindings(
    protocol: Mapping[str, Any],
    *,
    full: DAMGKStatePriorContextBinding,
    zero: DAMGKStatePriorContextBinding,
    shuffled: DAMGKStatePriorContextBinding,
) -> None:
    contract = protocol["binding_contract"]
    expected = {
        "state_prior_admission_id": full.admission_id,
        "admission_sha256": full.admission_sha256,
        "state_prior_id": full.state_prior_id,
        "context_artifact_sha256": full.context_artifact_sha256,
        "fixed_kernel_inputs_sha256": full.fixed_kernel_inputs_sha256,
        "context_values_sha256": {
            "full_state_prior": full.context_values_sha256,
            "zero_state_prior": zero.context_values_sha256,
            "shuffled_state_prior": shuffled.context_values_sha256,
        },
    }
    if contract != expected:
        raise ValueError("state_prior_transition_protocol_binding_contract_mismatch")
    controls = protocol["control_definitions"]
    if (
        controls["zero_state_prior"]["binding_control"] != zero.negative_control
        or controls["zero_state_prior"]["seed"] != zero.negative_control_seed
        or controls["shuffled_state_prior"]["binding_control"] != shuffled.negative_control
        or controls["shuffled_state_prior"]["seed"] != shuffled.negative_control_seed
    ):
        raise ValueError("state_prior_transition_protocol_control_binding_mismatch")


def _verify_prediction_artifacts(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    rows: list[dict[str, Any]],
    paired_input_sha256: str,
    bindings: Mapping[str, DAMGKStatePriorContextBinding],
    evidence_refs: tuple[str, ...],
    protocol: Mapping[str, Any],
    registration_receipt: Mapping[str, Any],
    opening_receipt: Mapping[str, Any],
    evaluation_created: datetime,
) -> dict[str, dict[str, Any]]:
    if set(artifacts) != set(TRANSITION_EVALUATION_METHODS):
        raise ValueError("state_prior_transition_prediction_artifact_set_mismatch")
    normalized: dict[str, dict[str, Any]] = {}
    model_hashes = set()
    protocol_sha256 = protocol["protocol_sha256"]
    model_contract = protocol["model_contract"]
    candidate_model_sha256 = model_contract["candidate_control_shared_model_sha256"]
    baseline_model_sha256 = model_contract["traditional_baseline_model_sha256"]
    registration_sha256 = registration_receipt["registration_receipt_sha256"]
    opening_sha256 = opening_receipt["holdout_opening_receipt_sha256"]
    holdout_manifest_sha256 = opening_receipt["holdout_manifest_sha256"]
    holdout_opened = _parse_aware_timestamp(opening_receipt["opened_at"])
    for method in TRANSITION_EVALUATION_METHODS:
        artifact = dict(artifacts[method])
        if set(artifact) != _PREDICTION_ARTIFACT_FIELDS:
            raise ValueError(f"state_prior_transition_{method}_artifact_field_set_mismatch")
        if not _nonempty_string(artifact.get("uri")) or artifact["uri"] not in evidence_refs:
            raise ValueError(f"state_prior_transition_{method}_artifact_evidence_missing")
        artifact_created = _parse_aware_timestamp(artifact.get("created_at"))
        if artifact_created is None:
            raise ValueError(f"state_prior_transition_{method}_created_at_invalid")
        if holdout_opened is None or artifact_created < holdout_opened:
            raise ValueError(f"state_prior_transition_{method}_created_before_holdout_opening")
        if artifact_created > evaluation_created:
            raise ValueError(f"state_prior_transition_{method}_created_after_evaluation")
        if artifact.get("paired_input_sha256") != paired_input_sha256:
            raise ValueError(f"state_prior_transition_{method}_paired_input_mismatch")
        if artifact.get("protocol_sha256") != protocol_sha256:
            raise ValueError(f"state_prior_transition_{method}_protocol_sha256_mismatch")
        if artifact.get("protocol_registration_receipt_sha256") != registration_sha256:
            raise ValueError(f"state_prior_transition_{method}_registration_sha256_mismatch")
        if artifact.get("holdout_opening_receipt_sha256") != opening_sha256:
            raise ValueError(f"state_prior_transition_{method}_opening_sha256_mismatch")
        if artifact.get("holdout_manifest_sha256") != holdout_manifest_sha256:
            raise ValueError(f"state_prior_transition_{method}_holdout_manifest_sha256_mismatch")
        expected_predictions = compute_state_prior_prediction_sha256(rows, method)
        if artifact.get("predictions_sha256") != expected_predictions:
            raise ValueError(f"state_prior_transition_{method}_predictions_sha256_mismatch")
        if not _valid_sha256(artifact.get("model_sha256")):
            raise ValueError(f"state_prior_transition_{method}_model_sha256_invalid")
        expected_model_sha256 = (
            baseline_model_sha256 if method == "traditional_baseline" else candidate_model_sha256
        )
        if artifact["model_sha256"] != expected_model_sha256:
            raise ValueError(f"state_prior_transition_{method}_model_sha256_mismatch")
        if method in bindings:
            binding = bindings[method]
            if artifact.get("context_values_sha256") != binding.context_values_sha256:
                raise ValueError(f"state_prior_transition_{method}_context_sha256_mismatch")
            model_hashes.add(artifact["model_sha256"])
        elif artifact.get("context_values_sha256") is not None:
            raise ValueError("state_prior_transition_baseline_must_not_use_state_prior_context")
        normalized[method] = artifact
    if len(model_hashes) != 1:
        raise ValueError("state_prior_transition_controls_must_share_model_parameters")
    return normalized


def _normalize_holdout_records(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(records, (str, bytes)) or not records:
        raise ValueError("state_prior_transition_holdout_records_required")
    rows: list[dict[str, Any]] = []
    seen = set()
    text_fields = (
        "sample_id",
        "split",
        "node_key",
        "action_id",
        "target_evidence_ref",
        "action_evidence_ref",
        "action_sha256",
        "forcing_sha256",
        "topology_sha256",
    )
    numeric_fields = (
        "target",
        "full_prediction",
        "zero_prediction",
        "shuffled_prediction",
        "baseline_prediction",
        "full_interval_lower",
        "full_interval_upper",
    )
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ValueError("state_prior_transition_holdout_record_must_be_object")
        row = dict(raw)
        for field in text_fields:
            if not _nonempty_string(row.get(field)):
                raise ValueError(f"state_prior_transition_{field}_required")
        if row["split"] not in REQUIRED_TRANSITION_HOLDOUT_SPLITS:
            raise ValueError("state_prior_transition_holdout_split_invalid")
        key = (row["split"], row["sample_id"])
        if key in seen:
            raise ValueError("state_prior_transition_duplicate_holdout_sample")
        seen.add(key)
        for field in numeric_fields:
            if not _finite_number(row.get(field)):
                raise ValueError(f"state_prior_transition_{field}_must_be_finite")
            row[field] = float(row[field])
        if not row["full_interval_lower"] <= row["full_prediction"] <= row["full_interval_upper"]:
            raise ValueError("state_prior_transition_prediction_interval_invalid")
        for field in ("action_sha256", "forcing_sha256", "topology_sha256"):
            if not _valid_sha256(row[field]):
                raise ValueError(f"state_prior_transition_{field}_invalid")
        rows.append(row)
    return rows


def _score_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "sample_count": 0,
            **{
                method: {"mae": math.inf, "rmse": math.inf}
                for method in TRANSITION_EVALUATION_METHODS
            },
        }
    target = np.asarray([row["target"] for row in rows], dtype=float)
    result: dict[str, Any] = {"sample_count": len(rows)}
    for method, field in _PREDICTION_FIELDS.items():
        prediction = np.asarray([row[field] for row in rows], dtype=float)
        error = prediction - target
        result[method] = {
            "mae": float(np.mean(np.abs(error))),
            "rmse": float(np.sqrt(np.mean(error**2))),
            "bias": float(np.mean(error)),
        }
    lower = np.asarray([row["full_interval_lower"] for row in rows], dtype=float)
    upper = np.asarray([row["full_interval_upper"] for row in rows], dtype=float)
    result["full_state_prior"].update(
        {
            "interval_coverage": float(np.mean((target >= lower) & (target <= upper))),
            "mean_interval_width": float(np.mean(upper - lower)),
        }
    )
    return result


def _beats_every_split(
    split_metrics: Mapping[str, Mapping[str, Any]],
    *,
    comparator: str,
    minimum_relative_improvement: float,
) -> bool:
    return all(
        _beats_with_margin(
            split_metrics[split]["full_state_prior"]["mae"],
            split_metrics[split][comparator]["mae"],
            minimum_relative_improvement,
        )
        for split in REQUIRED_TRANSITION_HOLDOUT_SPLITS
    )


def _paired_context_complete(rows: Sequence[Mapping[str, Any]], *, evidence_refs: set[str]) -> bool:
    return all(
        row["target_evidence_ref"] in evidence_refs
        and row["action_evidence_ref"] in evidence_refs
        and _valid_sha256(row["action_sha256"])
        and _valid_sha256(row["forcing_sha256"])
        and _valid_sha256(row["topology_sha256"])
        for row in rows
    )


def _action_support_passes(rows: Sequence[Mapping[str, Any]]) -> bool:
    future_actions = {
        row["action_id"] for row in rows if row["split"] == "future_action_conditioned"
    }
    return len(future_actions) >= 2


def _strict_leakage_audit_passes(
    audit: Mapping[str, Any],
    *,
    protocol_rules: Mapping[str, Any],
) -> bool:
    by_split = audit.get("by_split")
    if not isinstance(by_split, Mapping) or set(by_split) != set(
        REQUIRED_TRANSITION_HOLDOUT_SPLITS
    ):
        return False
    unseen = by_split["unseen_region"]
    low_sample = by_split["low_sample_region"]
    future = by_split["future_action_conditioned"]
    if not all(isinstance(value, Mapping) for value in (unseen, low_sample, future)):
        return False
    low_sample_count = low_sample.get("maximum_training_samples_per_holdout_region")
    low_sample_limit = low_sample.get("predeclared_maximum_training_samples")
    required_global = protocol_rules["global"]
    required_by_split = protocol_rules["by_split"]
    protocol_low_sample_limit = required_by_split["low_sample_region"][
        "predeclared_maximum_training_samples"
    ]
    return (
        audit.get("passed") is True
        and audit.get("train_holdout_sample_overlap_count")
        == required_global["train_holdout_sample_overlap_count"]
        and audit.get("state_prior_fit_used_holdout_targets")
        is required_global["state_prior_fit_used_holdout_targets"]
        and audit.get("normalization_fit_used_holdout")
        is required_global["normalization_fit_used_holdout"]
        and audit.get("action_outcomes_used_as_context")
        is required_global["action_outcomes_used_as_context"]
        and unseen.get("passed") is True
        and unseen.get("train_holdout_region_overlap_count")
        == required_by_split["unseen_region"]["train_holdout_region_overlap_count"]
        and low_sample.get("passed") is True
        and isinstance(low_sample_count, int)
        and not isinstance(low_sample_count, bool)
        and isinstance(low_sample_limit, int)
        and not isinstance(low_sample_limit, bool)
        and low_sample_limit == protocol_low_sample_limit
        and 0 <= low_sample_count <= low_sample_limit
        and future.get("passed") is True
        and future.get("future_ordering_verified")
        is required_by_split["future_action_conditioned"]["future_ordering_verified"]
        and future.get("action_outcome_pair_overlap_count")
        == required_by_split["future_action_conditioned"]["action_outcome_pair_overlap_count"]
    )


def _binding_confidence_level(binding: DAMGKStatePriorContextBinding) -> float:
    envelope = dict(binding.admission)["context_envelope"]
    uncertainty = envelope.get("uncertainty") or {}
    value = uncertainty.get("confidence_level")
    if not _valid_fraction(value, include_one=False) or value == 0.0:
        raise ValueError("state_prior_transition_binding_confidence_level_invalid")
    return float(value)


def _beats_with_margin(candidate: float, comparator: float, margin: float) -> bool:
    if not math.isfinite(candidate) or not math.isfinite(comparator):
        return False
    if comparator <= 0.0:
        return candidate < comparator
    return candidate <= comparator * (1.0 - margin)


def _optional_tensor_equal(left: torch.Tensor | None, right: torch.Tensor | None) -> bool:
    if left is None or right is None:
        return left is right
    return torch.equal(left, right)


def _claim_level(payload: Mapping[str, Any]) -> Any:
    boundary = payload.get("claim_boundary")
    return boundary.get("max_claim_level") if isinstance(boundary, Mapping) else None


def _unique_nonempty_strings(values: Sequence[Any], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"state_prior_transition_{field_name}_must_be_sequence")
    normalized = tuple(str(value).strip() for value in values)
    if not normalized or any(not value for value in normalized):
        raise ValueError(f"state_prior_transition_{field_name}_required")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"state_prior_transition_{field_name}_must_be_unique")
    return normalized


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not _nonempty_string(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _valid_fraction(value: Any, *, include_one: bool) -> bool:
    if not _finite_number(value):
        return False
    return 0.0 <= float(value) <= 1.0 if include_one else 0.0 <= float(value) < 1.0


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _json_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
