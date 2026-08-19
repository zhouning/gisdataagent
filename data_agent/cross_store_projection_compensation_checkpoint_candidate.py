"""Prepare non-writing checkpoint admission candidates for compensation receipts.

This layer combines a complete Provider receipt set with deployment-supplied
checkpoint predecessor identities.  It intentionally stops before constructing
or writing an authority ``ProjectionCheckpoint`` because the original sealed
repair plan and the live predecessor must still be admitted by the authority
owner.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_compensation_provider_receipt_set import (
    FederatedProjectionCompensationProviderReceiptValidationSet,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class FederatedProjectionCompensationCheckpointCandidateError(ValueError):
    """Checkpoint candidate evidence is incomplete or differs from its chain."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


class FederatedProjectionCompensationCheckpointPredecessor(_FrozenModel):
    """Deployment-side identity of the current checkpoint predecessor."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-checkpoint-predecessor.v1"
    position: int = Field(ge=0, le=31)
    tenant_id: TenantId
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    previous_checkpoint_sha256: Sha256 | None = None
    next_checkpoint_version: int = Field(ge=1, le=2**31 - 1)

    @model_validator(mode="after")
    def _version_chain(
        self,
    ) -> FederatedProjectionCompensationCheckpointPredecessor:
        if self.previous_checkpoint_sha256 is None and self.next_checkpoint_version != 1:
            raise ValueError("initial checkpoint candidate must use version 1")
        if self.previous_checkpoint_sha256 is not None and self.next_checkpoint_version < 2:
            raise ValueError("successor checkpoint candidate must advance the version")
        return self


class FederatedProjectionCompensationCheckpointCandidate(_FrozenModel):
    """One target checkpoint candidate, still outside authority."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-checkpoint-candidate.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    proposal_sha256: Sha256
    proposal_candidate_sha256: Sha256
    dispatch_intent_sha256: Sha256
    receipt_validation_set_sha256: Sha256
    plan_set_sha256: Sha256
    materialization_set_sha256: Sha256
    source_plan_sha256: Sha256
    source_resource_version_ref: NonEmptyText
    source_content_sha256: Sha256
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    target_exists: bool
    target_content_sha256: Sha256 | None
    target_row_count: int = Field(ge=0)
    provider_action: Literal["checkpoint", "rebuild", "delete"]
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    provider_receipt_sha256: Sha256
    provider_receipt_status: Literal["completed", "replayed", "checkpointed", "deleted"]
    previous_checkpoint_sha256: Sha256 | None = None
    next_checkpoint_version: int = Field(ge=1, le=2**31 - 1)
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    candidate_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_candidate(
        self,
    ) -> FederatedProjectionCompensationCheckpointCandidate:
        if self.target_exists != (self.target_content_sha256 is not None):
            raise ValueError("checkpoint candidate target content differs from existence")
        if not self.target_exists and self.target_row_count != 0:
            raise ValueError("deleted checkpoint candidate must have zero rows")
        if self.previous_checkpoint_sha256 is None and self.next_checkpoint_version != 1:
            raise ValueError("initial checkpoint candidate must use version 1")
        if self.previous_checkpoint_sha256 is not None and self.next_checkpoint_version < 2:
            raise ValueError("successor checkpoint candidate must advance the version")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"candidate_sha256"}),
            "candidate_sha256",
        )
        if self.candidate_sha256 != expected:
            raise ValueError("checkpoint candidate fingerprint is invalid")
        return self


class FederatedProjectionCompensationCheckpointCandidateSet(_FrozenModel):
    """All target candidates for one complete receipt validation set."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-checkpoint-candidate-set.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    dispatch_intent_sha256: Sha256
    receipt_validation_set_sha256: Sha256
    plan_set_sha256: Sha256
    materialization_set_sha256: Sha256
    candidates: tuple[FederatedProjectionCompensationCheckpointCandidate, ...] = Field(
        min_length=1, max_length=32
    )
    candidate_state: Literal["checkpoint_candidates_pending_authority_admission"] = (
        "checkpoint_candidates_pending_authority_admission"
    )
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    candidate_set_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_set(
        self,
    ) -> FederatedProjectionCompensationCheckpointCandidateSet:
        positions = tuple(candidate.position for candidate in self.candidates)
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("checkpoint candidate positions must be unique and ordered")
        for candidate in self.candidates:
            if (
                candidate.tenant_id != self.tenant_id
                or candidate.run_id != self.run_id
                or candidate.dispatch_intent_sha256 != self.dispatch_intent_sha256
                or candidate.receipt_validation_set_sha256 != self.receipt_validation_set_sha256
                or candidate.plan_set_sha256 != self.plan_set_sha256
                or candidate.materialization_set_sha256 != self.materialization_set_sha256
                or candidate.authority_admission_performed
                or candidate.authority_write_allowed
                or candidate.checkpoint_write_allowed
                or candidate.compensation_completion_allowed
            ):
                raise ValueError("checkpoint candidate differs from its set")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"candidate_set_sha256"}),
            "candidate_set_sha256",
        )
        if self.candidate_set_sha256 != expected:
            raise ValueError("checkpoint candidate set fingerprint is invalid")
        return self


def _validated_inputs(
    receipt_set: FederatedProjectionCompensationProviderReceiptValidationSet,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    predecessors: tuple[FederatedProjectionCompensationCheckpointPredecessor, ...],
) -> tuple[
    FederatedProjectionCompensationProviderReceiptValidationSet,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    tuple[FederatedProjectionCompensationCheckpointPredecessor, ...],
]:
    try:
        return (
            FederatedProjectionCompensationProviderReceiptValidationSet.model_validate(
                receipt_set.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderPlanSet.model_validate(
                plan_set.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderMaterializationSet.model_validate(
                materialization.model_dump(mode="python")
            ),
            tuple(
                FederatedProjectionCompensationCheckpointPredecessor.model_validate(
                    predecessor.model_dump(mode="python")
                )
                for predecessor in predecessors
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationCheckpointCandidateError(
            "checkpoint candidate input violates its sealed contract"
        ) from exc


def build_federated_compensation_checkpoint_candidate_set(
    receipt_set: FederatedProjectionCompensationProviderReceiptValidationSet,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    predecessors: tuple[FederatedProjectionCompensationCheckpointPredecessor, ...],
) -> FederatedProjectionCompensationCheckpointCandidateSet:
    """Build checkpoint evidence without constructing or writing authority state."""

    receipt_set, plan_set, materialization, predecessors = _validated_inputs(
        receipt_set,
        plan_set,
        materialization,
        predecessors,
    )
    if (
        receipt_set.tenant_id != plan_set.tenant_id
        or receipt_set.run_id != plan_set.run_id
        or receipt_set.plan_set_sha256 != plan_set.plan_set_sha256
        or receipt_set.materialization_set_sha256 != materialization.materialization_set_sha256
        or receipt_set.dispatch_intent_sha256 != plan_set.dispatch_intent_sha256
    ):
        raise FederatedProjectionCompensationCheckpointCandidateError(
            "checkpoint candidate chain identities differ"
        )
    predecessor_by_position = {item.position: item for item in predecessors}
    if len(predecessor_by_position) != len(predecessors):
        raise FederatedProjectionCompensationCheckpointCandidateError(
            "checkpoint predecessors must be unique"
        )
    positions = tuple(binding.position for binding in materialization.bindings)
    if set(predecessor_by_position) != set(positions):
        raise FederatedProjectionCompensationCheckpointCandidateError(
            "checkpoint predecessors must cover every materialization position"
        )
    plan_by_position = {binding.position: binding for binding in plan_set.plan_bindings}
    validation_by_binding = {
        validation.materialization_binding_sha256: validation
        for validation in receipt_set.receipt_validations
    }
    candidates: list[FederatedProjectionCompensationCheckpointCandidate] = []
    for binding in materialization.bindings:
        predecessor = predecessor_by_position[binding.position]
        plan = plan_by_position.get(binding.position)
        validation = validation_by_binding.get(binding.materialization_binding_sha256)
        if plan is None or validation is None:
            raise FederatedProjectionCompensationCheckpointCandidateError(
                "checkpoint candidate position lacks plan or receipt validation"
            )
        if (
            predecessor.tenant_id != receipt_set.tenant_id
            or predecessor.projection_id != binding.projection_id
            or predecessor.target_engine is not binding.target_engine
            or predecessor.target_ref != binding.target_ref
            or validation.target_exists != binding.expected_target_exists
            or validation.target_content_sha256 != binding.expected_target_content_sha256
            or validation.target_row_count != binding.expected_target_row_count
        ):
            raise FederatedProjectionCompensationCheckpointCandidateError(
                "checkpoint predecessor or receipt outcome differs from materialization"
            )
        values = {
            "tenant_id": receipt_set.tenant_id,
            "run_id": receipt_set.run_id,
            "position": binding.position,
            "proposal_sha256": receipt_set.proposal_sha256,
            "proposal_candidate_sha256": receipt_set.candidate_sha256,
            "dispatch_intent_sha256": receipt_set.dispatch_intent_sha256,
            "receipt_validation_set_sha256": receipt_set.validation_set_sha256,
            "plan_set_sha256": plan_set.plan_set_sha256,
            "materialization_set_sha256": materialization.materialization_set_sha256,
            "source_plan_sha256": plan.source_plan_sha256,
            "source_resource_version_ref": plan.source_resource_version_ref,
            "source_content_sha256": plan.source_content_sha256,
            "projection_id": binding.projection_id,
            "target_engine": binding.target_engine,
            "target_ref": binding.target_ref,
            "target_exists": validation.target_exists,
            "target_content_sha256": validation.target_content_sha256,
            "target_row_count": validation.target_row_count,
            "provider_action": binding.provider_action,
            "provider_plan_sha256": validation.provider_plan_sha256,
            "provider_idempotency_key": validation.provider_idempotency_key,
            "provider_receipt_sha256": validation.provider_receipt_sha256,
            "provider_receipt_status": validation.receipt_status,
            "previous_checkpoint_sha256": predecessor.previous_checkpoint_sha256,
            "next_checkpoint_version": predecessor.next_checkpoint_version,
            "authority_admission_performed": False,
            "authority_write_allowed": False,
            "checkpoint_write_allowed": False,
            "compensation_completion_allowed": False,
        }
        candidates.append(
            FederatedProjectionCompensationCheckpointCandidate(
                **values,
                candidate_sha256=_fingerprint(
                    FederatedProjectionCompensationCheckpointCandidate.schema_id,
                    values,
                    "candidate_sha256",
                ),
            )
        )
    values = {
        "tenant_id": receipt_set.tenant_id,
        "run_id": receipt_set.run_id,
        "dispatch_intent_sha256": receipt_set.dispatch_intent_sha256,
        "receipt_validation_set_sha256": receipt_set.validation_set_sha256,
        "plan_set_sha256": plan_set.plan_set_sha256,
        "materialization_set_sha256": materialization.materialization_set_sha256,
        "candidates": tuple(candidates),
        "candidate_state": "checkpoint_candidates_pending_authority_admission",
        "authority_admission_performed": False,
        "authority_write_allowed": False,
        "checkpoint_write_allowed": False,
        "compensation_completion_allowed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationCheckpointCandidateSet.model_construct(
        **values,
        candidate_set_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"candidate_set_sha256"})
    return FederatedProjectionCompensationCheckpointCandidateSet(
        **values,
        candidate_set_sha256=_fingerprint(
            FederatedProjectionCompensationCheckpointCandidateSet.schema_id,
            normalized,
            "candidate_set_sha256",
        ),
    )


__all__ = [
    "FederatedProjectionCompensationCheckpointCandidateError",
    "FederatedProjectionCompensationCheckpointPredecessor",
    "FederatedProjectionCompensationCheckpointCandidate",
    "FederatedProjectionCompensationCheckpointCandidateSet",
    "build_federated_compensation_checkpoint_candidate_set",
]
