"""Bind admitted state-prior features to DAM-GK node context."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

import torch

from ..geospatial_kernel.state_prior_admission import (
    STATE_PRIOR_ADMISSION_SCHEMA,
    validate_state_prior_admission,
)
from .contracts import DAMGKBatch, DAMGKConfig

DAM_GK_STATE_PRIOR_BINDING_SCHEMA = "gwm.geospatial_kernel.dam_gk_state_prior_context_binding.v1"
STATE_PRIOR_CONTEXT_CONTROLS = ("zero", "shuffle_nodes")


@dataclass(frozen=True)
class DAMGKStatePriorContextBinding:
    """A hash-bound DAM-GK batch/config pair with admitted prior context."""

    schema: str
    batch: DAMGKBatch
    config: DAMGKConfig
    node_keys: tuple[str, ...]
    context_feature_names: tuple[str, ...]
    state_prior_feature_names: tuple[str, ...]
    state_prior_feature_indices: tuple[int, ...]
    admission: Mapping[str, Any]
    admission_id: str
    admission_sha256: str
    state_prior_id: str
    context_ref: str
    context_artifact_sha256: str
    fixed_kernel_inputs_sha256: str
    evidence_refs: tuple[str, ...]
    calibration_evidence_refs: tuple[str, ...]
    context_values_sha256: str
    negative_control: str | None = None
    negative_control_seed: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "admission": copy.deepcopy(dict(self.admission)),
            "admission_id": self.admission_id,
            "admission_sha256": self.admission_sha256,
            "state_prior_id": self.state_prior_id,
            "context_ref": self.context_ref,
            "context_artifact_sha256": self.context_artifact_sha256,
            "fixed_kernel_inputs_sha256": self.fixed_kernel_inputs_sha256,
            "node_keys": list(self.node_keys),
            "context_feature_names": list(self.context_feature_names),
            "state_prior_feature_names": list(self.state_prior_feature_names),
            "state_prior_feature_indices": list(self.state_prior_feature_indices),
            "context_values_sha256": self.context_values_sha256,
            "evidence_refs": list(self.evidence_refs),
            "calibration_evidence_refs": list(self.calibration_evidence_refs),
            "negative_control": self.negative_control,
            "negative_control_seed": self.negative_control_seed,
            "tensor_contract": {
                "node_count": self.batch.node_state.shape[0],
                "base_context_dim": (
                    len(self.context_feature_names) - len(self.state_prior_feature_names)
                ),
                "state_prior_context_dim": len(self.state_prior_feature_names),
                "bound_context_dim": self.config.context_dim,
                "static_origin_context_repeated_across_rollout_steps": (
                    self.batch.node_context_by_step is not None
                ),
            },
            "preservation_boundary": {
                "node_state_unchanged": True,
                "node_action_unchanged": True,
                "existing_context_channels_unchanged": True,
                "edge_index_unchanged": True,
                "edge_features_unchanged": True,
                "edge_types_unchanged": True,
                "edge_valid_mask_unchanged": True,
                "teacher_state_unchanged": True,
                "region_context_unchanged": True,
            },
            "claim_boundary": {
                "max_claim_level": "bounded_support",
                "state_reconstruction_context_only": True,
                "transition_skill_improvement_claim": False,
                "policy_causal_effect_claim": False,
                "general_geospatial_world_model_validation_claim": False,
            },
        }


def bind_admitted_state_prior_node_context(
    *,
    batch: DAMGKBatch,
    config: DAMGKConfig,
    admission: Mapping[str, Any],
    node_keys: Sequence[str],
    base_context_feature_names: Sequence[str],
    state_prior_feature_names: Sequence[str],
    state_prior_values: torch.Tensor,
    context_artifact_sha256: str,
) -> DAMGKStatePriorContextBinding:
    """Append an admitted static state prior without changing kernel semantics."""

    batch.validate(config)
    admission_payload = dict(admission)
    admission_validation = validate_state_prior_admission(admission_payload)
    if not admission_validation["valid"]:
        raise ValueError(
            "dam_gk_state_prior_admission_invalid:" + ",".join(admission_validation["errors"])
        )
    if admission_payload.get("schema") != STATE_PRIOR_ADMISSION_SCHEMA:
        raise ValueError("dam_gk_state_prior_admission_schema_mismatch")
    if admission_payload.get("status") != "admitted" or (
        admission_payload.get("state_prior_context_ready") is not True
    ):
        raise ValueError("dam_gk_state_prior_admission_blocked")
    if admission_payload.get("enabled_support_levels") != ["learned_calibrated"]:
        raise ValueError("dam_gk_state_prior_support_level_not_enabled")

    envelope = admission_payload.get("context_envelope")
    if not isinstance(envelope, dict) or "node_context" not in (envelope.get("allowed_uses") or []):
        raise ValueError("dam_gk_state_prior_node_context_use_not_allowed")
    if context_artifact_sha256 != envelope.get("context_sha256") or not _valid_sha256(
        context_artifact_sha256
    ):
        raise ValueError("dam_gk_state_prior_context_artifact_sha256_mismatch")

    normalized_nodes = _unique_nonempty_strings(node_keys, "node_keys")
    node_count = batch.node_state.shape[0]
    if len(normalized_nodes) != node_count:
        raise ValueError("dam_gk_state_prior_node_count_mismatch")
    base_features = _unique_nonempty_strings(
        base_context_feature_names, "base_context_feature_names", allow_empty=True
    )
    if len(base_features) != config.context_dim:
        raise ValueError("dam_gk_state_prior_base_context_feature_count_mismatch")

    declared_prior_features = _unique_nonempty_strings(
        envelope.get("state_variables") or [], "state_prior_feature_names"
    )
    prior_features = _unique_nonempty_strings(
        state_prior_feature_names, "state_prior_feature_names"
    )
    if prior_features != declared_prior_features:
        raise ValueError("dam_gk_state_prior_feature_order_mismatch")
    if set(base_features).intersection(prior_features):
        raise ValueError("dam_gk_state_prior_feature_name_collision")
    _validate_prior_values(
        state_prior_values,
        node_count=node_count,
        feature_count=len(prior_features),
        batch=batch,
    )

    values = state_prior_values.detach().clone()
    if batch.node_context is None:
        node_context = values
    else:
        node_context = torch.cat((batch.node_context, values), dim=1)

    context_by_step = batch.node_context_by_step
    if context_by_step is not None:
        repeated = values[:, None, :].expand(-1, config.horizon, -1)
        context_by_step = torch.cat((context_by_step, repeated), dim=2)
        if not torch.equal(node_context, context_by_step[:, 0]):
            raise ValueError("dam_gk_state_prior_origin_context_mismatch")

    bound_batch = replace(
        batch,
        node_context=node_context,
        node_context_by_step=context_by_step,
    )
    bound_config = replace(
        config,
        context_dim=config.context_dim + len(prior_features),
    )
    bound_batch.validate(bound_config)
    _verify_non_context_tensors_unchanged(batch, bound_batch, config.context_dim)

    all_features = (*base_features, *prior_features)
    indices = tuple(range(config.context_dim, bound_config.context_dim))
    binding = DAMGKStatePriorContextBinding(
        schema=DAM_GK_STATE_PRIOR_BINDING_SCHEMA,
        batch=bound_batch,
        config=bound_config,
        node_keys=normalized_nodes,
        context_feature_names=all_features,
        state_prior_feature_names=prior_features,
        state_prior_feature_indices=indices,
        admission=copy.deepcopy(admission_payload),
        admission_id=str(admission_payload["admission_id"]),
        admission_sha256=_json_sha256(admission_payload),
        state_prior_id=str(admission_payload["state_prior_id"]),
        context_ref=str(envelope["context_ref"]),
        context_artifact_sha256=context_artifact_sha256,
        fixed_kernel_inputs_sha256=_fixed_kernel_inputs_sha256(
            bound_batch,
            base_config=config,
            base_context_dim=config.context_dim,
        ),
        evidence_refs=tuple(admission_payload["evidence_refs"]),
        calibration_evidence_refs=tuple(admission_payload["calibration_evidence_refs"]),
        context_values_sha256=_context_values_sha256(
            values,
            node_keys=normalized_nodes,
            feature_names=prior_features,
        ),
    )
    verify_dam_gk_state_prior_context_binding(binding)
    return binding


def with_state_prior_context_control(
    binding: DAMGKStatePriorContextBinding,
    *,
    mode: str,
    seed: int = 0,
) -> DAMGKStatePriorContextBinding:
    """Apply a deterministic control to prior channels and nothing else."""

    verify_dam_gk_state_prior_context_binding(binding)
    if mode not in STATE_PRIOR_CONTEXT_CONTROLS:
        raise ValueError("unsupported_dam_gk_state_prior_context_control")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("dam_gk_state_prior_control_seed_invalid")

    batch = binding.batch
    indices = torch.tensor(
        binding.state_prior_feature_indices,
        dtype=torch.long,
        device=batch.node_context.device,
    )
    node_context = batch.node_context.clone()
    context_by_step = (
        None if batch.node_context_by_step is None else batch.node_context_by_step.clone()
    )
    if mode == "zero":
        node_context[:, indices] = 0.0
        if context_by_step is not None:
            context_by_step[:, :, indices] = 0.0
    else:
        generator = torch.Generator(device="cpu").manual_seed(seed)
        permutation = torch.randperm(batch.node_state.shape[0], generator=generator)
        if len(permutation) < 2:
            raise ValueError("dam_gk_state_prior_shuffle_requires_multiple_nodes")
        if torch.equal(permutation, torch.arange(len(permutation))):
            permutation = torch.roll(permutation, shifts=1)
        device_permutation = permutation.to(node_context.device)
        node_context[:, indices] = batch.node_context[device_permutation[:, None], indices[None, :]]
        if context_by_step is not None:
            context_by_step[:, :, indices] = batch.node_context_by_step[
                device_permutation[:, None, None],
                torch.arange(
                    binding.config.horizon,
                    device=context_by_step.device,
                )[None, :, None],
                indices[None, None, :],
            ]

    controlled_batch = replace(
        batch,
        node_context=node_context,
        node_context_by_step=context_by_step,
    )
    _verify_non_context_tensors_unchanged(
        batch,
        controlled_batch,
        len(binding.context_feature_names) - len(binding.state_prior_feature_names),
    )
    current_values = node_context[:, indices]
    controlled = replace(
        binding,
        batch=controlled_batch,
        context_values_sha256=_context_values_sha256(
            current_values,
            node_keys=binding.node_keys,
            feature_names=binding.state_prior_feature_names,
        ),
        negative_control=mode,
        negative_control_seed=seed,
    )
    verify_dam_gk_state_prior_context_binding(controlled)
    return controlled


def verify_dam_gk_state_prior_context_binding(
    binding: DAMGKStatePriorContextBinding,
) -> None:
    """Reject inconsistent or manually forged state-prior binding receipts."""

    if binding.schema != DAM_GK_STATE_PRIOR_BINDING_SCHEMA:
        raise ValueError("dam_gk_state_prior_binding_schema_mismatch")
    admission_payload = dict(binding.admission)
    admission_validation = validate_state_prior_admission(admission_payload)
    if not admission_validation["valid"] or (
        admission_payload.get("state_prior_context_ready") is not True
    ):
        raise ValueError("dam_gk_state_prior_binding_admission_invalid")
    if _json_sha256(admission_payload) != binding.admission_sha256:
        raise ValueError("dam_gk_state_prior_binding_admission_digest_mismatch")
    envelope = admission_payload.get("context_envelope") or {}
    if (
        binding.admission_id != admission_payload.get("admission_id")
        or binding.state_prior_id != admission_payload.get("state_prior_id")
        or binding.context_ref != envelope.get("context_ref")
        or binding.context_artifact_sha256 != envelope.get("context_sha256")
        or binding.state_prior_feature_names != tuple(envelope.get("state_variables") or ())
        or binding.evidence_refs != tuple(admission_payload.get("evidence_refs") or ())
        or binding.calibration_evidence_refs
        != tuple(admission_payload.get("calibration_evidence_refs") or ())
    ):
        raise ValueError("dam_gk_state_prior_binding_admission_metadata_mismatch")
    binding.batch.validate(binding.config)
    node_count = binding.batch.node_state.shape[0]
    if len(binding.node_keys) != node_count or len(set(binding.node_keys)) != node_count:
        raise ValueError("dam_gk_state_prior_binding_node_keys_invalid")
    if not binding.state_prior_feature_names:
        raise ValueError("dam_gk_state_prior_binding_features_required")
    if len(set(binding.context_feature_names)) != len(binding.context_feature_names):
        raise ValueError("dam_gk_state_prior_binding_feature_names_not_unique")
    if len(binding.context_feature_names) != binding.config.context_dim:
        raise ValueError("dam_gk_state_prior_binding_context_feature_count_mismatch")
    if binding.context_feature_names[-len(binding.state_prior_feature_names) :] != (
        binding.state_prior_feature_names
    ):
        raise ValueError("dam_gk_state_prior_binding_features_must_be_appended")
    expected_indices = tuple(
        range(
            binding.config.context_dim - len(binding.state_prior_feature_names),
            binding.config.context_dim,
        )
    )
    if binding.state_prior_feature_indices != expected_indices:
        raise ValueError("dam_gk_state_prior_binding_feature_indices_invalid")
    if binding.negative_control not in {None, *STATE_PRIOR_CONTEXT_CONTROLS}:
        raise ValueError("dam_gk_state_prior_binding_control_invalid")
    if binding.negative_control is None and binding.negative_control_seed is not None:
        raise ValueError("dam_gk_state_prior_binding_unexpected_control_seed")
    if binding.negative_control is not None and binding.negative_control_seed is None:
        raise ValueError("dam_gk_state_prior_binding_control_seed_required")
    for field_name in (
        "admission_id",
        "admission_sha256",
        "state_prior_id",
        "context_ref",
        "context_artifact_sha256",
        "fixed_kernel_inputs_sha256",
        "context_values_sha256",
    ):
        if not str(getattr(binding, field_name)).strip():
            raise ValueError(f"dam_gk_state_prior_binding_{field_name}_required")
    if (
        not _valid_sha256(binding.admission_sha256)
        or not _valid_sha256(binding.context_artifact_sha256)
        or not _valid_sha256(binding.fixed_kernel_inputs_sha256)
        or not _valid_sha256(binding.context_values_sha256)
    ):
        raise ValueError("dam_gk_state_prior_binding_sha256_invalid")
    if not binding.evidence_refs or not binding.calibration_evidence_refs:
        raise ValueError("dam_gk_state_prior_binding_evidence_required")

    base_context_dim = binding.config.context_dim - len(binding.state_prior_feature_names)
    expected_fixed_digest = _fixed_kernel_inputs_sha256(
        binding.batch,
        base_config=replace(binding.config, context_dim=base_context_dim),
        base_context_dim=base_context_dim,
    )
    if expected_fixed_digest != binding.fixed_kernel_inputs_sha256:
        raise ValueError("dam_gk_state_prior_binding_fixed_inputs_digest_mismatch")

    indices = torch.tensor(
        binding.state_prior_feature_indices,
        dtype=torch.long,
        device=binding.batch.node_context.device,
    )
    values = binding.batch.node_context[:, indices]
    expected_digest = _context_values_sha256(
        values,
        node_keys=binding.node_keys,
        feature_names=binding.state_prior_feature_names,
    )
    if expected_digest != binding.context_values_sha256:
        raise ValueError("dam_gk_state_prior_binding_context_digest_mismatch")
    if binding.batch.node_context_by_step is not None:
        repeated = values[:, None, :].expand(-1, binding.config.horizon, -1)
        if not torch.equal(binding.batch.node_context_by_step[:, :, indices], repeated):
            raise ValueError("dam_gk_state_prior_binding_step_context_mismatch")


def _validate_prior_values(
    values: torch.Tensor,
    *,
    node_count: int,
    feature_count: int,
    batch: DAMGKBatch,
) -> None:
    if not isinstance(values, torch.Tensor):
        raise TypeError("dam_gk_state_prior_values_must_be_tensor")
    if values.shape != (node_count, feature_count):
        raise ValueError("dam_gk_state_prior_values_shape_mismatch")
    if values.dtype not in {torch.float32, torch.float64}:
        raise ValueError("dam_gk_state_prior_values_dtype_invalid")
    if not torch.isfinite(values).all():
        raise ValueError("dam_gk_state_prior_values_must_be_finite")
    reference = batch.node_context if batch.node_context is not None else batch.node_context_by_step
    if reference is not None and (
        values.dtype != reference.dtype or values.device != reference.device
    ):
        raise ValueError("dam_gk_state_prior_values_dtype_or_device_mismatch")


def _verify_non_context_tensors_unchanged(
    before: DAMGKBatch,
    after: DAMGKBatch,
    base_context_dim: int,
) -> None:
    for field_name in (
        "node_state",
        "node_action",
        "edge_index",
        "edge_features",
        "edge_types",
        "teacher_state_by_step",
        "region_context",
        "edge_valid_mask",
    ):
        if not _optional_tensor_equal(getattr(before, field_name), getattr(after, field_name)):
            raise ValueError(f"dam_gk_state_prior_binding_changed_{field_name}")
    if before.node_context is not None and not torch.equal(
        before.node_context[:, :base_context_dim],
        after.node_context[:, :base_context_dim],
    ):
        raise ValueError("dam_gk_state_prior_binding_changed_base_node_context")
    if before.node_context_by_step is not None and not torch.equal(
        before.node_context_by_step[:, :, :base_context_dim],
        after.node_context_by_step[:, :, :base_context_dim],
    ):
        raise ValueError("dam_gk_state_prior_binding_changed_base_step_context")


def _optional_tensor_equal(left: torch.Tensor | None, right: torch.Tensor | None) -> bool:
    if left is None or right is None:
        return left is right
    return torch.equal(left, right)


def _unique_nonempty_strings(
    values: Sequence[Any], field_name: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"dam_gk_state_prior_{field_name}_must_be_sequence")
    normalized = tuple(str(value).strip() for value in values)
    if (not normalized and not allow_empty) or any(not value for value in normalized):
        raise ValueError(f"dam_gk_state_prior_{field_name}_required")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"dam_gk_state_prior_{field_name}_must_be_unique")
    return normalized


def _context_values_sha256(
    values: torch.Tensor,
    *,
    node_keys: Sequence[str],
    feature_names: Sequence[str],
) -> str:
    tensor = values.detach().cpu().contiguous()
    metadata = json.dumps(
        {
            "dtype": str(tensor.dtype),
            "shape": list(tensor.shape),
            "node_keys": list(node_keys),
            "feature_names": list(feature_names),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(metadata)
    digest.update(tensor.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _fixed_kernel_inputs_sha256(
    batch: DAMGKBatch,
    *,
    base_config: DAMGKConfig,
    base_context_dim: int,
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            asdict(base_config),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    tensors = {
        "node_state": batch.node_state,
        "node_action": batch.node_action,
        "node_context": (
            None if batch.node_context is None else batch.node_context[:, :base_context_dim]
        ),
        "node_context_by_step": (
            None
            if batch.node_context_by_step is None
            else batch.node_context_by_step[:, :, :base_context_dim]
        ),
        "edge_index": batch.edge_index,
        "edge_features": batch.edge_features,
        "edge_types": batch.edge_types,
        "teacher_state_by_step": batch.teacher_state_by_step,
        "region_context": batch.region_context,
        "edge_valid_mask": batch.edge_valid_mask,
    }
    for name, value in tensors.items():
        digest.update(name.encode("ascii"))
        if value is None:
            digest.update(b"null")
            continue
        tensor = value.detach().cpu().contiguous()
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode("ascii"))
        digest.update(tensor.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
