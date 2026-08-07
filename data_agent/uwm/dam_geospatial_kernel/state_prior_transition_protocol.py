"""Frozen preregistration for DAM-GK state-prior transition evaluation."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import torch

from .state_prior_context_adapter import (
    DAMGKStatePriorContextBinding,
    verify_dam_gk_state_prior_context_binding,
)

DAM_GK_STATE_PRIOR_TRANSITION_PROTOCOL_SCHEMA = (
    "gwm.geospatial_kernel.state_prior_transition_protocol.v1"
)

REQUIRED_TRANSITION_HOLDOUT_SPLITS = (
    "unseen_region",
    "low_sample_region",
    "future_action_conditioned",
)
TRANSITION_EVALUATION_METHODS = (
    "full_state_prior",
    "zero_state_prior",
    "shuffled_state_prior",
    "traditional_baseline",
)
TRANSITION_PRIMARY_METRIC = "mae"
TRANSITION_PROTOCOL_PERMITTED_CLAIM = (
    "state_prior_context_improves_transition_skill_under_paired_strict_holdout"
)

_SOURCE_EVIDENCE_KINDS = {
    "observed_holdout",
    "public_proxy",
    "synthetic_fixture",
}
_ZERO_CONTROL_OPERATION = "replace_state_prior_channels_with_zero"
_SHUFFLE_CONTROL_OPERATION = "seeded_node_permutation_of_state_prior_channels"
_CLAIM_BOUNDARY = {
    "max_claim_level": "bounded_support",
    "permitted_claim": TRANSITION_PROTOCOL_PERMITTED_CLAIM,
    "scope": "paired_state_prior_context_transition_skill_only",
    "policy_causal_effect_claim": False,
    "action_conditioned_dynamics_claim": False,
    "general_geospatial_world_model_validation_claim": False,
    "autonomous_planning_superiority_claim": False,
}


def build_dam_gk_state_prior_transition_protocol(
    *,
    protocol_id: str,
    created_at: str,
    frozen_at: str,
    holdout_access_not_before: str,
    full_binding: DAMGKStatePriorContextBinding,
    zero_binding: DAMGKStatePriorContextBinding,
    shuffled_binding: DAMGKStatePriorContextBinding,
    candidate_control_model_sha256: str,
    traditional_baseline_model_sha256: str,
    source_evidence_kind: str,
    evidence_refs: Sequence[str],
    minimum_samples_per_split: int = 10,
    minimum_relative_improvement: float = 0.01,
    coverage_tolerance: float = 0.05,
    low_sample_maximum_training_samples: int = 5,
) -> dict[str, Any]:
    """Freeze all confirmatory choices before the audited holdout is opened."""

    if not _nonempty_string(protocol_id):
        raise ValueError("state_prior_transition_protocol_id_required")
    created = _require_aware_timestamp(created_at, "created_at")
    frozen = _require_aware_timestamp(frozen_at, "frozen_at")
    holdout_access_not_before_time = _require_aware_timestamp(
        holdout_access_not_before, "holdout_access_not_before"
    )
    if created > frozen:
        raise ValueError("state_prior_transition_protocol_frozen_before_creation")
    if frozen >= holdout_access_not_before_time:
        raise ValueError("state_prior_transition_protocol_frozen_after_holdout_access")
    if source_evidence_kind not in _SOURCE_EVIDENCE_KINDS:
        raise ValueError("state_prior_transition_protocol_source_evidence_kind_invalid")
    if (
        not isinstance(minimum_samples_per_split, int)
        or isinstance(minimum_samples_per_split, bool)
        or minimum_samples_per_split <= 0
    ):
        raise ValueError("state_prior_transition_protocol_minimum_samples_invalid")
    if not _valid_fraction(minimum_relative_improvement, include_one=False):
        raise ValueError("state_prior_transition_protocol_improvement_threshold_invalid")
    if not _valid_fraction(coverage_tolerance, include_one=False):
        raise ValueError("state_prior_transition_protocol_coverage_tolerance_invalid")
    if (
        not isinstance(low_sample_maximum_training_samples, int)
        or isinstance(low_sample_maximum_training_samples, bool)
        or low_sample_maximum_training_samples < 0
    ):
        raise ValueError("state_prior_transition_protocol_low_sample_limit_invalid")
    if not _valid_sha256(candidate_control_model_sha256):
        raise ValueError("state_prior_transition_protocol_candidate_model_sha256_invalid")
    if not _valid_sha256(traditional_baseline_model_sha256):
        raise ValueError("state_prior_transition_protocol_baseline_model_sha256_invalid")
    if candidate_control_model_sha256 == traditional_baseline_model_sha256:
        raise ValueError("state_prior_transition_protocol_baseline_model_must_be_distinct")

    _verify_protocol_bindings(full_binding, zero_binding, shuffled_binding)
    if zero_binding.negative_control_seed != shuffled_binding.negative_control_seed:
        raise ValueError("state_prior_transition_protocol_control_seed_mismatch")
    control_seed = zero_binding.negative_control_seed
    if control_seed is None:
        raise ValueError("state_prior_transition_protocol_control_seed_required")

    confidence_level = _binding_confidence_level(full_binding)
    if coverage_tolerance >= confidence_level:
        raise ValueError("state_prior_transition_protocol_coverage_tolerance_exceeds_confidence")
    normalized_evidence = _unique_nonempty_strings(evidence_refs, "evidence_refs")
    if any(ref not in normalized_evidence for ref in full_binding.evidence_refs):
        raise ValueError("state_prior_transition_protocol_binding_evidence_missing")

    protocol = {
        "schema": DAM_GK_STATE_PRIOR_TRANSITION_PROTOCOL_SCHEMA,
        "version": "0.1",
        "protocol_id": str(protocol_id),
        "created_at": str(created_at),
        "frozen_at": str(frozen_at),
        "holdout_access_not_before": str(holdout_access_not_before),
        "source_evidence_kind": source_evidence_kind,
        "evidence_refs": list(normalized_evidence),
        "binding_contract": {
            "state_prior_admission_id": full_binding.admission_id,
            "admission_sha256": full_binding.admission_sha256,
            "state_prior_id": full_binding.state_prior_id,
            "context_artifact_sha256": full_binding.context_artifact_sha256,
            "fixed_kernel_inputs_sha256": full_binding.fixed_kernel_inputs_sha256,
            "context_values_sha256": {
                "full_state_prior": full_binding.context_values_sha256,
                "zero_state_prior": zero_binding.context_values_sha256,
                "shuffled_state_prior": shuffled_binding.context_values_sha256,
            },
        },
        "evaluation_design": {
            "required_splits": list(REQUIRED_TRANSITION_HOLDOUT_SPLITS),
            "methods": list(TRANSITION_EVALUATION_METHODS),
            "primary_metric": TRANSITION_PRIMARY_METRIC,
            "minimum_samples_per_split": minimum_samples_per_split,
            "minimum_relative_improvement": float(minimum_relative_improvement),
            "confidence_level": confidence_level,
            "coverage_tolerance": float(coverage_tolerance),
            "minimum_coverage_threshold": confidence_level - float(coverage_tolerance),
            "paired_inputs_fixed": [
                "target",
                "action",
                "forcing",
                "topology",
                "node_key",
                "holdout_split",
            ],
        },
        "control_definitions": {
            "zero_state_prior": {
                "binding_control": "zero",
                "operation": _ZERO_CONTROL_OPERATION,
                "seed": control_seed,
            },
            "shuffled_state_prior": {
                "binding_control": "shuffle_nodes",
                "operation": _SHUFFLE_CONTROL_OPERATION,
                "seed": control_seed,
            },
        },
        "model_contract": {
            "candidate_control_shared_model_sha256": candidate_control_model_sha256,
            "traditional_baseline_model_sha256": traditional_baseline_model_sha256,
        },
        "split_specific_leakage_rules": _expected_leakage_rules(
            low_sample_maximum_training_samples
        ),
        "freeze_assertion": {
            "holdout_accessed_before_freeze": False,
            "thresholds_frozen_before_holdout": True,
            "model_hashes_frozen_before_holdout": True,
            "control_definitions_frozen_before_holdout": True,
        },
        "claim_boundary": copy.deepcopy(_CLAIM_BOUNDARY),
    }
    protocol["protocol_sha256"] = compute_state_prior_transition_protocol_sha256(protocol)
    validation = validate_dam_gk_state_prior_transition_protocol(protocol)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_transition_protocol:" + ";".join(validation["errors"])
        )
    return protocol


def validate_dam_gk_state_prior_transition_protocol(payload: Any) -> dict[str, Any]:
    """Validate the frozen design and recompute its canonical digest."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["protocol_must_be_a_dictionary"]}
    errors: list[str] = []
    expected_fields = {
        "schema",
        "version",
        "protocol_id",
        "created_at",
        "frozen_at",
        "holdout_access_not_before",
        "source_evidence_kind",
        "evidence_refs",
        "binding_contract",
        "evaluation_design",
        "control_definitions",
        "model_contract",
        "split_specific_leakage_rules",
        "freeze_assertion",
        "claim_boundary",
        "protocol_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("protocol_field_set_mismatch")
    if payload.get("schema") != DAM_GK_STATE_PRIOR_TRANSITION_PROTOCOL_SCHEMA:
        errors.append("protocol_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("protocol_version_mismatch")
    if not _nonempty_string(payload.get("protocol_id")):
        errors.append("protocol_id_required")

    created = _parse_aware_timestamp(payload.get("created_at"))
    frozen = _parse_aware_timestamp(payload.get("frozen_at"))
    holdout_access_not_before = _parse_aware_timestamp(payload.get("holdout_access_not_before"))
    if created is None:
        errors.append("protocol_created_at_invalid")
    if frozen is None:
        errors.append("protocol_frozen_at_invalid")
    if holdout_access_not_before is None:
        errors.append("protocol_holdout_access_not_before_invalid")
    if created is not None and frozen is not None and created > frozen:
        errors.append("protocol_frozen_before_creation")
    if (
        frozen is not None
        and holdout_access_not_before is not None
        and frozen >= holdout_access_not_before
    ):
        errors.append("protocol_frozen_after_holdout_access")
    if payload.get("source_evidence_kind") not in _SOURCE_EVIDENCE_KINDS:
        errors.append("protocol_source_evidence_kind_invalid")
    if not _nonempty_strings(payload.get("evidence_refs")):
        errors.append("protocol_evidence_refs_invalid")

    binding = payload.get("binding_contract")
    expected_binding_fields = {
        "state_prior_admission_id",
        "admission_sha256",
        "state_prior_id",
        "context_artifact_sha256",
        "fixed_kernel_inputs_sha256",
        "context_values_sha256",
    }
    if not isinstance(binding, dict) or set(binding) != expected_binding_fields:
        errors.append("protocol_binding_contract_invalid")
    else:
        if not _nonempty_string(binding.get("state_prior_admission_id")):
            errors.append("protocol_state_prior_admission_id_required")
        if not _nonempty_string(binding.get("state_prior_id")):
            errors.append("protocol_state_prior_id_required")
        for field in (
            "admission_sha256",
            "context_artifact_sha256",
            "fixed_kernel_inputs_sha256",
        ):
            if not _valid_sha256(binding.get(field)):
                errors.append(f"protocol_{field}_invalid")
        context_hashes = binding.get("context_values_sha256")
        if not isinstance(context_hashes, dict) or set(context_hashes) != {
            "full_state_prior",
            "zero_state_prior",
            "shuffled_state_prior",
        }:
            errors.append("protocol_context_values_sha256_set_invalid")
        elif any(not _valid_sha256(value) for value in context_hashes.values()):
            errors.append("protocol_context_values_sha256_invalid")

    design = payload.get("evaluation_design")
    expected_design_fields = {
        "required_splits",
        "methods",
        "primary_metric",
        "minimum_samples_per_split",
        "minimum_relative_improvement",
        "confidence_level",
        "coverage_tolerance",
        "minimum_coverage_threshold",
        "paired_inputs_fixed",
    }
    if not isinstance(design, dict) or set(design) != expected_design_fields:
        errors.append("protocol_evaluation_design_invalid")
    else:
        _validate_evaluation_design(design, errors)

    controls = payload.get("control_definitions")
    if not _valid_control_definitions(controls):
        errors.append("protocol_control_definitions_invalid")

    models = payload.get("model_contract")
    if not isinstance(models, dict) or set(models) != {
        "candidate_control_shared_model_sha256",
        "traditional_baseline_model_sha256",
    }:
        errors.append("protocol_model_contract_invalid")
    else:
        candidate_hash = models.get("candidate_control_shared_model_sha256")
        baseline_hash = models.get("traditional_baseline_model_sha256")
        if not _valid_sha256(candidate_hash):
            errors.append("protocol_candidate_model_sha256_invalid")
        if not _valid_sha256(baseline_hash):
            errors.append("protocol_baseline_model_sha256_invalid")
        if candidate_hash == baseline_hash:
            errors.append("protocol_baseline_model_must_be_distinct")

    leakage_rules = payload.get("split_specific_leakage_rules")
    low_sample_limit = _low_sample_limit(leakage_rules)
    if low_sample_limit is None or leakage_rules != _expected_leakage_rules(low_sample_limit):
        errors.append("protocol_split_specific_leakage_rules_invalid")
    if payload.get("freeze_assertion") != {
        "holdout_accessed_before_freeze": False,
        "thresholds_frozen_before_holdout": True,
        "model_hashes_frozen_before_holdout": True,
        "control_definitions_frozen_before_holdout": True,
    }:
        errors.append("protocol_freeze_assertion_invalid")
    if payload.get("claim_boundary") != _CLAIM_BOUNDARY:
        errors.append("protocol_claim_boundary_invalid")

    protocol_sha256 = payload.get("protocol_sha256")
    if not _valid_sha256(protocol_sha256):
        errors.append("protocol_sha256_invalid")
    elif protocol_sha256 != compute_state_prior_transition_protocol_sha256(payload):
        errors.append("protocol_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def compute_state_prior_transition_protocol_sha256(payload: Mapping[str, Any]) -> str:
    """Hash a protocol canonically while excluding its own digest field."""

    content = {key: value for key, value in dict(payload).items() if key != "protocol_sha256"}
    encoded = json.dumps(
        content,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_protocol_bindings(
    full: DAMGKStatePriorContextBinding,
    zero: DAMGKStatePriorContextBinding,
    shuffled: DAMGKStatePriorContextBinding,
) -> None:
    for binding in (full, zero, shuffled):
        verify_dam_gk_state_prior_context_binding(binding)
    if full.negative_control is not None:
        raise ValueError("state_prior_transition_protocol_full_binding_must_not_be_control")
    if zero.negative_control != "zero":
        raise ValueError("state_prior_transition_protocol_zero_binding_required")
    if shuffled.negative_control != "shuffle_nodes":
        raise ValueError("state_prior_transition_protocol_shuffled_binding_required")
    shared_fields = (
        "config",
        "admission_id",
        "admission_sha256",
        "state_prior_id",
        "context_ref",
        "context_artifact_sha256",
        "fixed_kernel_inputs_sha256",
        "node_keys",
        "context_feature_names",
        "state_prior_feature_names",
        "state_prior_feature_indices",
        "evidence_refs",
        "calibration_evidence_refs",
    )
    for control in (zero, shuffled):
        if any(getattr(control, field) != getattr(full, field) for field in shared_fields):
            raise ValueError("state_prior_transition_protocol_binding_metadata_mismatch")
    indices = torch.tensor(
        full.state_prior_feature_indices,
        dtype=torch.long,
        device=full.batch.node_context.device,
    )
    full_values = full.batch.node_context[:, indices]
    zero_values = zero.batch.node_context[:, indices]
    shuffled_values = shuffled.batch.node_context[:, indices]
    if torch.count_nonzero(zero_values).item() != 0:
        raise ValueError("state_prior_transition_protocol_zero_control_not_zero")
    if torch.equal(full_values, shuffled_values):
        raise ValueError("state_prior_transition_protocol_shuffle_control_ineffective")
    if not torch.equal(
        torch.sort(full_values, dim=0).values,
        torch.sort(shuffled_values, dim=0).values,
    ):
        raise ValueError("state_prior_transition_protocol_shuffle_control_not_permutation")


def _validate_evaluation_design(design: Mapping[str, Any], errors: list[str]) -> None:
    if design.get("required_splits") != list(REQUIRED_TRANSITION_HOLDOUT_SPLITS):
        errors.append("protocol_required_splits_mismatch")
    if design.get("methods") != list(TRANSITION_EVALUATION_METHODS):
        errors.append("protocol_methods_mismatch")
    if design.get("primary_metric") != TRANSITION_PRIMARY_METRIC:
        errors.append("protocol_primary_metric_mismatch")
    minimum_samples = design.get("minimum_samples_per_split")
    if (
        not isinstance(minimum_samples, int)
        or isinstance(minimum_samples, bool)
        or minimum_samples <= 0
    ):
        errors.append("protocol_minimum_samples_invalid")
    if not _valid_fraction(design.get("minimum_relative_improvement"), include_one=False):
        errors.append("protocol_minimum_relative_improvement_invalid")
    confidence = design.get("confidence_level")
    tolerance = design.get("coverage_tolerance")
    if not _valid_fraction(confidence, include_one=False) or confidence == 0.0:
        errors.append("protocol_confidence_level_invalid")
    if not _valid_fraction(tolerance, include_one=False):
        errors.append("protocol_coverage_tolerance_invalid")
    if _finite_number(confidence) and _finite_number(tolerance):
        expected_threshold = float(confidence) - float(tolerance)
        if tolerance >= confidence:
            errors.append("protocol_coverage_tolerance_exceeds_confidence")
        threshold = design.get("minimum_coverage_threshold")
        if not _finite_number(threshold) or not math.isclose(
            float(threshold), expected_threshold, rel_tol=0.0, abs_tol=1e-12
        ):
            errors.append("protocol_minimum_coverage_threshold_inconsistent")
    if design.get("paired_inputs_fixed") != [
        "target",
        "action",
        "forcing",
        "topology",
        "node_key",
        "holdout_split",
    ]:
        errors.append("protocol_paired_inputs_fixed_mismatch")


def _valid_control_definitions(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "zero_state_prior",
        "shuffled_state_prior",
    }:
        return False
    zero = value["zero_state_prior"]
    shuffled = value["shuffled_state_prior"]
    if not isinstance(zero, dict) or not isinstance(shuffled, dict):
        return False
    expected_fields = {"binding_control", "operation", "seed"}
    if set(zero) != expected_fields or set(shuffled) != expected_fields:
        return False
    seed = zero.get("seed")
    return (
        isinstance(seed, int)
        and not isinstance(seed, bool)
        and shuffled.get("seed") == seed
        and zero.get("binding_control") == "zero"
        and zero.get("operation") == _ZERO_CONTROL_OPERATION
        and shuffled.get("binding_control") == "shuffle_nodes"
        and shuffled.get("operation") == _SHUFFLE_CONTROL_OPERATION
    )


def _expected_leakage_rules(low_sample_limit: int) -> dict[str, Any]:
    return {
        "global": {
            "train_holdout_sample_overlap_count": 0,
            "state_prior_fit_used_holdout_targets": False,
            "normalization_fit_used_holdout": False,
            "action_outcomes_used_as_context": False,
        },
        "by_split": {
            "unseen_region": {
                "train_holdout_region_overlap_count": 0,
            },
            "low_sample_region": {
                "predeclared_maximum_training_samples": low_sample_limit,
            },
            "future_action_conditioned": {
                "future_ordering_verified": True,
                "action_outcome_pair_overlap_count": 0,
            },
        },
    }


def _low_sample_limit(value: Any) -> int | None:
    if not isinstance(value, Mapping):
        return None
    by_split = value.get("by_split")
    if not isinstance(by_split, Mapping):
        return None
    low_sample = by_split.get("low_sample_region")
    if not isinstance(low_sample, Mapping):
        return None
    limit = low_sample.get("predeclared_maximum_training_samples")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        return None
    return limit


def _binding_confidence_level(binding: DAMGKStatePriorContextBinding) -> float:
    envelope = dict(binding.admission)["context_envelope"]
    uncertainty = envelope.get("uncertainty") or {}
    value = uncertainty.get("confidence_level")
    if not _valid_fraction(value, include_one=False) or value == 0.0:
        raise ValueError("state_prior_transition_protocol_binding_confidence_level_invalid")
    return float(value)


def _require_aware_timestamp(value: Any, field: str) -> datetime:
    parsed = _parse_aware_timestamp(value)
    if parsed is None:
        raise ValueError(f"state_prior_transition_protocol_{field}_invalid")
    return parsed


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


def _unique_nonempty_strings(values: Sequence[Any], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"state_prior_transition_protocol_{field_name}_must_be_sequence")
    normalized = tuple(str(value).strip() for value in values)
    if not normalized or any(not value for value in normalized):
        raise ValueError(f"state_prior_transition_protocol_{field_name}_required")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"state_prior_transition_protocol_{field_name}_must_be_unique")
    return normalized


def _nonempty_strings(value: Any) -> bool:
    return bool(
        isinstance(value, list)
        and value
        and all(_nonempty_string(item) for item in value)
        and len(value) == len(set(value))
    )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
