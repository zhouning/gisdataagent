"""Read-only admission of sealed repair plans into checkpoint evidence.

This module closes the last pre-authority gap in the federated compensation
chain.  A deployment can provide a complete set of sealed
``ProjectionRepairPlan`` objects and the current checkpoint predecessor
summaries, but this layer only verifies their identities and emits a
deterministic preview.  It never constructs a ``ProjectionCheckpoint`` and
never invokes the PostgreSQL authority.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_checkpoint_candidate import (
    FederatedProjectionCompensationCheckpointCandidateSet,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_consistency import ProjectionEngine, ProjectionRepairPlan
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class FederatedProjectionCompensationCheckpointAdmissionError(ValueError):
    """The complete repair-plan admission chain cannot be trusted."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


class FederatedProjectionCompensationCheckpointAdmissionRequest(_FrozenModel):
    """All immutable inputs required for a read-only authority precheck."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-checkpoint-admission-request.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    candidate_set: FederatedProjectionCompensationCheckpointCandidateSet
    plan_set: FederatedProjectionCompensationProviderPlanSet
    materialization: FederatedProjectionCompensationProviderMaterializationSet
    repair_plans: tuple[ProjectionRepairPlan, ...] = Field(min_length=1, max_length=32)
    admission_state: Literal["pending_read_only_authority_precheck"] = (
        "pending_read_only_authority_precheck"
    )
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    request_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_request(
        self,
    ) -> FederatedProjectionCompensationCheckpointAdmissionRequest:
        if (
            self.tenant_id != self.candidate_set.tenant_id
            or self.tenant_id != self.plan_set.tenant_id
            or self.tenant_id != self.materialization.tenant_id
            or self.run_id != self.candidate_set.run_id
            or self.run_id != self.plan_set.run_id
            or self.run_id != self.materialization.run_id
        ):
            raise ValueError("checkpoint admission request tenant or run differs")
        if (
            self.authority_admission_performed
            or self.authority_write_allowed
            or self.checkpoint_write_allowed
            or self.compensation_completion_allowed
        ):
            raise ValueError("checkpoint admission request cannot authorize writes")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("checkpoint admission request fingerprint is invalid")
        return self


class FederatedProjectionCompensationCheckpointAdmissionItem(_FrozenModel):
    """One plan/candidate pair that passed all pre-authority checks."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-checkpoint-admission-item.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    candidate_sha256: Sha256
    plan_sha256: Sha256
    plan_idempotency_key: Sha256
    source_resource_version_ref: NonEmptyText
    source_content_sha256: Sha256
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    action: Literal["checkpoint", "rebuild", "delete"]
    target_exists: bool
    target_content_sha256: Sha256 | None
    target_row_count: int = Field(ge=0)
    previous_checkpoint_sha256: Sha256 | None
    next_checkpoint_version: int = Field(ge=1)
    authority_predecessor_state: Literal["deployment_supplied_current_predecessor"] = (
        "deployment_supplied_current_predecessor"
    )
    admission_checks: tuple[str, ...] = Field(min_length=1)
    admission_state: Literal["validated_pending_authority_write"] = (
        "validated_pending_authority_write"
    )
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    item_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_item(
        self,
    ) -> FederatedProjectionCompensationCheckpointAdmissionItem:
        if self.target_exists != (self.target_content_sha256 is not None):
            raise ValueError("admission target state is incomplete")
        if not self.target_exists and self.target_row_count != 0:
            raise ValueError("deleted admission target must have zero rows")
        if self.previous_checkpoint_sha256 is None and self.next_checkpoint_version != 1:
            raise ValueError("initial admission predecessor must use version 1")
        if self.previous_checkpoint_sha256 is not None and self.next_checkpoint_version < 2:
            raise ValueError("successor admission predecessor must advance the version")
        if self.admission_checks != tuple(sorted(set(self.admission_checks))):
            raise ValueError("admission checks must be unique and sorted")
        if (
            self.authority_admission_performed
            or self.authority_write_allowed
            or self.checkpoint_write_allowed
            or self.compensation_completion_allowed
        ):
            raise ValueError("admission item cannot authorize writes")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"item_sha256"}),
            "item_sha256",
        )
        if self.item_sha256 != expected:
            raise ValueError("admission item fingerprint is invalid")
        return self


class FederatedProjectionCompensationCheckpointAdmissionPreview(_FrozenModel):
    """Deterministic, non-writing result of the authority precheck."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-checkpoint-admission-preview.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    request_sha256: Sha256
    candidate_set_sha256: Sha256
    plan_set_sha256: Sha256
    materialization_set_sha256: Sha256
    items: tuple[FederatedProjectionCompensationCheckpointAdmissionItem, ...] = Field(
        min_length=1, max_length=32
    )
    admission_state: Literal["validated_pending_authority_write"] = (
        "validated_pending_authority_write"
    )
    all_repair_plans_admitted: Literal[True] = True
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    preview_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_preview(
        self,
    ) -> FederatedProjectionCompensationCheckpointAdmissionPreview:
        positions = tuple(item.position for item in self.items)
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("admission preview positions must be unique and ordered")
        for item in self.items:
            if (
                item.tenant_id != self.tenant_id
                or item.run_id != self.run_id
                or item.authority_admission_performed
                or item.authority_write_allowed
                or item.checkpoint_write_allowed
                or item.compensation_completion_allowed
            ):
                raise ValueError("admission item differs from preview")
        if (
            self.authority_admission_performed
            or self.authority_write_allowed
            or self.checkpoint_write_allowed
            or self.compensation_completion_allowed
        ):
            raise ValueError("admission preview cannot authorize writes")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"preview_sha256"}),
            "preview_sha256",
        )
        if self.preview_sha256 != expected:
            raise ValueError("admission preview fingerprint is invalid")
        return self


def _validated_inputs(
    candidate_set: FederatedProjectionCompensationCheckpointCandidateSet,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
) -> tuple[
    FederatedProjectionCompensationCheckpointCandidateSet,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    tuple[ProjectionRepairPlan, ...],
]:
    try:
        return (
            FederatedProjectionCompensationCheckpointCandidateSet.model_validate(
                candidate_set.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderPlanSet.model_validate(
                plan_set.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderMaterializationSet.model_validate(
                materialization.model_dump(mode="python")
            ),
            tuple(
                ProjectionRepairPlan.model_validate(plan.model_dump(mode="python"))
                for plan in repair_plans
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationCheckpointAdmissionError(
            "checkpoint admission input violates a sealed contract"
        ) from exc


def _assert_chain(
    candidate_set: FederatedProjectionCompensationCheckpointCandidateSet,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
) -> tuple[dict[int, Any], dict[int, Any], dict[int, ProjectionRepairPlan]]:
    if (
        candidate_set.plan_set_sha256 != plan_set.plan_set_sha256
        or candidate_set.materialization_set_sha256 != materialization.materialization_set_sha256
        or materialization.plan_set_sha256 != plan_set.plan_set_sha256
        or len(candidate_set.candidates) != len(plan_set.plan_bindings)
        or len(plan_set.plan_bindings) != len(materialization.bindings)
    ):
        raise FederatedProjectionCompensationCheckpointAdmissionError(
            "checkpoint admission chain identities differ"
        )
    candidates = {item.position: item for item in candidate_set.candidates}
    plans_by_position = {item.position: item for item in plan_set.plan_bindings}
    if len(candidates) != len(candidate_set.candidates) or len(plans_by_position) != len(
        plan_set.plan_bindings
    ):
        raise FederatedProjectionCompensationCheckpointAdmissionError(
            "checkpoint admission positions must be unique"
        )
    if set(candidates) != set(plans_by_position):
        raise FederatedProjectionCompensationCheckpointAdmissionError(
            "checkpoint admission positions differ between candidate and plan set"
        )
    materialization_by_position = {item.position: item for item in materialization.bindings}
    if set(materialization_by_position) != set(candidates):
        raise FederatedProjectionCompensationCheckpointAdmissionError(
            "checkpoint admission positions differ from materialization"
        )
    plans_by_hash: dict[str, ProjectionRepairPlan] = {}
    for plan in repair_plans:
        if plan.plan_sha256 in plans_by_hash:
            raise FederatedProjectionCompensationCheckpointAdmissionError(
                "repair plans must contain each plan_sha256 exactly once"
            )
        plans_by_hash[plan.plan_sha256] = plan
    if set(plans_by_hash) != {item.source_plan_sha256 for item in candidate_set.candidates}:
        raise FederatedProjectionCompensationCheckpointAdmissionError(
            "complete repair plan set does not cover every candidate exactly once"
        )

    for position, candidate in candidates.items():
        binding = plans_by_position[position]
        materialized = materialization_by_position[position]
        plan = plans_by_hash.get(candidate.source_plan_sha256)
        if plan is None:
            raise FederatedProjectionCompensationCheckpointAdmissionError(
                "candidate source plan is missing from the complete repair plan set"
            )
        if (
            binding.source_plan_sha256 != plan.plan_sha256
            or candidate.source_plan_sha256 != binding.source_plan_sha256
            or binding.source_resource_version_ref != plan.desired_state.source_resource_version_ref
            or binding.source_content_sha256 != plan.desired_state.source_content_sha256
            or candidate.source_resource_version_ref != binding.source_resource_version_ref
            or candidate.source_content_sha256 != binding.source_content_sha256
        ):
            raise FederatedProjectionCompensationCheckpointAdmissionError(
                "repair plan fingerprint or source version/content differs from plan binding"
            )
        if plan.action not in {"checkpoint", "rebuild", "delete"}:
            raise FederatedProjectionCompensationCheckpointAdmissionError(
                "fail-closed repair plans cannot be admitted as checkpoints"
            )
        desired = plan.desired_state
        observation = plan.observation
        assessment = plan.assessment
        if (
            plan.tenant_id != candidate.tenant_id
            or desired.tenant_id != candidate.tenant_id
            or plan.projection_id != desired.projection_id
            or plan.target_engine is not desired.target_engine
            or plan.target_ref != desired.target_ref
            or observation.tenant_id != desired.tenant_id
            or observation.projection_id != desired.projection_id
            or observation.target_engine is not desired.target_engine
            or observation.target_ref != desired.target_ref
            or assessment.tenant_id != desired.tenant_id
            or assessment.projection_id != desired.projection_id
            or assessment.target_engine is not desired.target_engine
            or assessment.target_ref != desired.target_ref
            or desired.projection_id != candidate.projection_id
            or materialized.projection_id != desired.projection_id
            or candidate.projection_id != materialized.projection_id
            or desired.target_engine.value != candidate.target_engine.value
            or desired.target_ref != candidate.target_ref
            or plan.action != candidate.provider_action
            or binding.target_engine is not desired.target_engine
            or binding.target_ref != desired.target_ref
        ):
            raise FederatedProjectionCompensationCheckpointAdmissionError(
                "repair plan projection identity or action differs from candidate"
            )
        allowed_receipt_statuses = {
            "checkpoint": {"checkpointed", "replayed"},
            "rebuild": {"completed", "replayed"},
            "delete": {"deleted", "replayed"},
        }
        if candidate.provider_receipt_status not in allowed_receipt_statuses[plan.action]:
            raise FederatedProjectionCompensationCheckpointAdmissionError(
                "candidate receipt status differs from repair action"
            )
        if (
            desired.target_exists != candidate.target_exists
            or desired.expected_target_content_sha256 != candidate.target_content_sha256
            or desired.expected_row_count != candidate.target_row_count
            or desired.target_exists != materialized.expected_target_exists
            or desired.expected_target_content_sha256 != materialized.expected_target_content_sha256
            or desired.expected_row_count != materialized.expected_target_row_count
        ):
            raise FederatedProjectionCompensationCheckpointAdmissionError(
                "repair plan desired target state differs from materialization or candidate"
            )
        if (
            plan.previous_checkpoint_sha256 != candidate.previous_checkpoint_sha256
            or plan.next_checkpoint_version != candidate.next_checkpoint_version
        ):
            raise FederatedProjectionCompensationCheckpointAdmissionError(
                "repair plan checkpoint predecessor or version differs from candidate"
            )
        if (
            materialized.plan_binding_sha256 != binding.plan_binding_sha256
            or materialized.provider_action != candidate.provider_action
            or materialized.provider_plan_sha256 != candidate.provider_plan_sha256
            or materialized.provider_idempotency_key != candidate.provider_idempotency_key
        ):
            raise FederatedProjectionCompensationCheckpointAdmissionError(
                "candidate provider identity differs from materialization"
            )
    return candidates, materialization_by_position, plans_by_hash


def build_federated_compensation_checkpoint_admission_request(
    candidate_set: FederatedProjectionCompensationCheckpointCandidateSet,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
) -> FederatedProjectionCompensationCheckpointAdmissionRequest:
    """Validate complete sealed plans and package a non-writing request."""

    candidate_set, plan_set, materialization, repair_plans = _validated_inputs(
        candidate_set,
        plan_set,
        materialization,
        repair_plans,
    )
    _assert_chain(candidate_set, plan_set, materialization, repair_plans)
    values = {
        "tenant_id": candidate_set.tenant_id,
        "run_id": candidate_set.run_id,
        "candidate_set": candidate_set,
        "plan_set": plan_set,
        "materialization": materialization,
        "repair_plans": repair_plans,
        "admission_state": "pending_read_only_authority_precheck",
        "authority_admission_performed": False,
        "authority_write_allowed": False,
        "checkpoint_write_allowed": False,
        "compensation_completion_allowed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationCheckpointAdmissionRequest.model_construct(
        **values,
        request_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"request_sha256"})
    return FederatedProjectionCompensationCheckpointAdmissionRequest(
        **values,
        request_sha256=_fingerprint(
            FederatedProjectionCompensationCheckpointAdmissionRequest.schema_id,
            normalized,
            "request_sha256",
        ),
    )


def preview_federated_compensation_checkpoint_admission(
    request: FederatedProjectionCompensationCheckpointAdmissionRequest,
) -> FederatedProjectionCompensationCheckpointAdmissionPreview:
    """Return a deterministic admission preview without authority access."""

    try:
        request = FederatedProjectionCompensationCheckpointAdmissionRequest.model_validate(
            request.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationCheckpointAdmissionError(
            "checkpoint admission request violates its sealed contract"
        ) from exc
    candidates, _, plans_by_hash = _assert_chain(
        request.candidate_set,
        request.plan_set,
        request.materialization,
        request.repair_plans,
    )
    plan_bindings = {binding.position: binding for binding in request.plan_set.plan_bindings}
    items: list[FederatedProjectionCompensationCheckpointAdmissionItem] = []
    checks = (
        "candidate_plan_hash",
        "checkpoint_predecessor",
        "checkpoint_version",
        "desired_target_state",
        "projection_identity",
        "source_content_sha256",
        "source_resource_version",
    )
    for position in sorted(candidates):
        candidate = candidates[position]
        plan = plans_by_hash[candidate.source_plan_sha256]
        binding = plan_bindings[position]
        desired = plan.desired_state
        values = {
            "tenant_id": request.tenant_id,
            "run_id": request.run_id,
            "position": position,
            "candidate_sha256": candidate.candidate_sha256,
            "plan_sha256": plan.plan_sha256,
            "plan_idempotency_key": plan.plan_idempotency_key,
            "source_resource_version_ref": desired.source_resource_version_ref,
            "source_content_sha256": desired.source_content_sha256,
            "projection_id": desired.projection_id,
            "target_engine": desired.target_engine,
            "target_ref": desired.target_ref,
            "action": plan.action,
            "target_exists": desired.target_exists,
            "target_content_sha256": desired.expected_target_content_sha256,
            "target_row_count": desired.expected_row_count,
            "previous_checkpoint_sha256": plan.previous_checkpoint_sha256,
            "next_checkpoint_version": plan.next_checkpoint_version,
            "authority_predecessor_state": "deployment_supplied_current_predecessor",
            "admission_checks": checks,
            "admission_state": "validated_pending_authority_write",
            "authority_admission_performed": False,
            "authority_write_allowed": False,
            "checkpoint_write_allowed": False,
            "compensation_completion_allowed": False,
        }
        if binding.source_plan_sha256 != candidate.source_plan_sha256:
            raise FederatedProjectionCompensationCheckpointAdmissionError(
                "repair plan position binding differs from candidate"
            )
        items.append(
            FederatedProjectionCompensationCheckpointAdmissionItem(
                **values,
                item_sha256=_fingerprint(
                    FederatedProjectionCompensationCheckpointAdmissionItem.schema_id,
                    values,
                    "item_sha256",
                ),
            )
        )
    values = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "request_sha256": request.request_sha256,
        "candidate_set_sha256": request.candidate_set.candidate_set_sha256,
        "plan_set_sha256": request.plan_set.plan_set_sha256,
        "materialization_set_sha256": request.materialization.materialization_set_sha256,
        "items": tuple(items),
        "admission_state": "validated_pending_authority_write",
        "all_repair_plans_admitted": True,
        "authority_admission_performed": False,
        "authority_write_allowed": False,
        "checkpoint_write_allowed": False,
        "compensation_completion_allowed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationCheckpointAdmissionPreview.model_construct(
        **values,
        preview_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"preview_sha256"})
    return FederatedProjectionCompensationCheckpointAdmissionPreview(
        **values,
        preview_sha256=_fingerprint(
            FederatedProjectionCompensationCheckpointAdmissionPreview.schema_id,
            normalized,
            "preview_sha256",
        ),
    )


def build_federated_compensation_checkpoint_admission_preview(
    candidate_set: FederatedProjectionCompensationCheckpointCandidateSet,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
) -> FederatedProjectionCompensationCheckpointAdmissionPreview:
    """Convenience API: validate a request and return its read-only preview."""

    request = build_federated_compensation_checkpoint_admission_request(
        candidate_set,
        plan_set,
        materialization,
        repair_plans,
    )
    return preview_federated_compensation_checkpoint_admission(request)


__all__ = [
    "FederatedProjectionCompensationCheckpointAdmissionError",
    "FederatedProjectionCompensationCheckpointAdmissionRequest",
    "FederatedProjectionCompensationCheckpointAdmissionItem",
    "FederatedProjectionCompensationCheckpointAdmissionPreview",
    "build_federated_compensation_checkpoint_admission_request",
    "preview_federated_compensation_checkpoint_admission",
    "build_federated_compensation_checkpoint_admission_preview",
]
