"""Aggregate complete compensation receipt evidence without authority writes.

The aggregate revalidates the dispatch, deployment plan, materialization, and
every Provider-native receipt validation as one chain.  A complete set is only
an authority-admission candidate; this module never invokes a Provider, writes
a checkpoint, or marks compensation complete.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
)
from .cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderOutcomeStatus,
    FederatedCompensationRunResult,
    FederatedCompensationRunState,
    FederatedCompensationRunValidationError,
    build_federated_compensation_run_bindings,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_compensation_provider_receipt import (
    FederatedProjectionCompensationProviderReceiptValidation,
)
from .platform_contracts import (
    NonEmptyText,
    ResourceURNText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)


class FederatedProjectionCompensationProviderReceiptSetError(ValueError):
    """Provider receipts do not form one complete, current evidence chain."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


class FederatedProjectionCompensationProviderReceiptValidationSet(_FrozenModel):
    """Complete receipt evidence awaiting a separate authority decision."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-receipt-validation-set.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    proposal_sha256: Sha256
    candidate_sha256: Sha256
    source_snapshot_sha256: Sha256
    dispatch_intent_sha256: Sha256
    execution_approval_case_ref: ResourceURNText
    review_approval_case_ref: ResourceURNText
    execution_authorization_sha256: Sha256
    review_binding_sha256: Sha256
    plan_set_sha256: Sha256
    adapter_resolution_sha256: Sha256
    adapter_id: NonEmptyText
    adapter_semantic_version: str
    adapter_sha256: Sha256
    implementation_artifact_sha256: Sha256
    materialization_set_sha256: Sha256
    receipt_validations: tuple[FederatedProjectionCompensationProviderReceiptValidation, ...] = (
        Field(min_length=1, max_length=32)
    )
    receipt_count: int = Field(ge=1, le=32)
    receipt_set_state: Literal["complete_provider_receipts_pending_authority_admission"] = (
        "complete_provider_receipts_pending_authority_admission"
    )
    provider_receipts_complete: Literal[True] = True
    authority_admission_performed: Literal[False] = False
    authority_write_allowed: Literal[False] = False
    checkpoint_write_allowed: Literal[False] = False
    compensation_completion_allowed: Literal[False] = False
    provider_invocation_performed_by_aggregator: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    validation_set_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_set(
        self,
    ) -> FederatedProjectionCompensationProviderReceiptValidationSet:
        if self.execution_approval_case_ref == self.review_approval_case_ref:
            raise ValueError("receipt set ApprovalCase references must differ")
        for reference in (
            self.execution_approval_case_ref,
            self.review_approval_case_ref,
        ):
            identity = parse_resource_urn(reference)
            if (
                identity["tenant_id"] != self.tenant_id
                or identity["resource_kind"] != "approval_case"
            ):
                raise ValueError("receipt set ApprovalCase tenant differs")
        if self.receipt_count != len(self.receipt_validations):
            raise ValueError("receipt set count differs from validations")
        identities = tuple(
            validation.materialization_binding_sha256 for validation in self.receipt_validations
        )
        if len(set(identities)) != len(identities):
            raise ValueError("receipt set materialization identities must be unique")
        plan_bindings = tuple(
            validation.plan_binding_sha256 for validation in self.receipt_validations
        )
        if len(set(plan_bindings)) != len(plan_bindings):
            raise ValueError("receipt set plan identities must be unique")
        receipt_hashes = tuple(
            validation.provider_receipt_sha256 for validation in self.receipt_validations
        )
        if len(set(receipt_hashes)) != len(receipt_hashes):
            raise ValueError("receipt set Provider receipt identities must be unique")
        for validation in self.receipt_validations:
            if (
                validation.tenant_id != self.tenant_id
                or validation.materialization_set_sha256 != self.materialization_set_sha256
                or validation.validation_state != "validated_not_authority_admitted"
                or validation.authority_write_allowed
                or validation.provider_execution_performed
                or validation.receipt_is_authority_record
            ):
                raise ValueError("receipt validation differs from its aggregate set")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"validation_set_sha256"}),
            "validation_set_sha256",
        )
        if self.validation_set_sha256 != expected:
            raise ValueError("provider receipt validation set fingerprint is invalid")
        return self


def _validated_inputs(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    validations: tuple[FederatedProjectionCompensationProviderReceiptValidation, ...],
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    tuple[FederatedProjectionCompensationProviderReceiptValidation, ...],
]:
    try:
        return (
            FederatedProjectionCompensationDispatchIntent.model_validate(
                intent.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderPlanSet.model_validate(
                plan_set.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderMaterializationSet.model_validate(
                materialization.model_dump(mode="python")
            ),
            tuple(
                FederatedProjectionCompensationProviderReceiptValidation.model_validate(
                    validation.model_dump(mode="python")
                )
                for validation in validations
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "provider receipt set input violates its sealed contract"
        ) from exc


def _assert_dispatch_plan_chain(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
) -> None:
    if (
        plan_set.tenant_id != intent.tenant_id
        or plan_set.run_id != intent.run_id
        or plan_set.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or plan_set.candidate_action is not intent.candidate_action
        or len(plan_set.plan_bindings) != len(intent.plan_bindings)
    ):
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "provider receipt plan set differs from dispatch intent"
        )
    for source, plan in zip(
        intent.plan_bindings,
        plan_set.plan_bindings,
        strict=True,
    ):
        if (
            plan.position != source.position
            or plan.source_plan_sha256 != source.plan_sha256
            or plan.source_resource_version_ref != source.source_resource_version_ref
            or plan.source_content_sha256 != source.source_content_sha256
            or plan.target_engine.value != source.target_engine
            or plan.target_ref != source.target_ref
        ):
            raise FederatedProjectionCompensationProviderReceiptSetError(
                "provider receipt source plan differs from dispatch intent"
            )


def _assert_plan_materialization_chain(
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
) -> None:
    if (
        materialization.tenant_id != plan_set.tenant_id
        or materialization.run_id != plan_set.run_id
        or materialization.plan_set_sha256 != plan_set.plan_set_sha256
        or materialization.adapter_id != plan_set.adapter_id
        or materialization.adapter_semantic_version != plan_set.adapter_semantic_version
        or materialization.adapter_sha256 != plan_set.adapter_sha256
        or materialization.implementation_artifact_sha256 != plan_set.implementation_artifact_sha256
        or len(materialization.bindings) != len(plan_set.plan_bindings)
    ):
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "provider receipt materialization differs from plan set"
        )
    for plan, binding in zip(
        plan_set.plan_bindings,
        materialization.bindings,
        strict=True,
    ):
        if (
            binding.position != plan.position
            or binding.plan_binding_sha256 != plan.plan_binding_sha256
            or binding.target_engine is not plan.target_engine
            or binding.target_ref != plan.target_ref
            or binding.provider_action != plan.provider_action
            or binding.receipt_schema_id != plan.receipt_schema_id
            or binding.provider_idempotency_key != plan.provider_idempotency_key
        ):
            raise FederatedProjectionCompensationProviderReceiptSetError(
                "provider receipt materialization binding differs from plan"
            )


def build_federated_compensation_provider_receipt_validation_set(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    validations: tuple[FederatedProjectionCompensationProviderReceiptValidation, ...],
) -> FederatedProjectionCompensationProviderReceiptValidationSet:
    """Seal complete receipt evidence as a non-writing admission candidate."""

    intent, plan_set, materialization, validations = _validated_inputs(
        intent,
        plan_set,
        materialization,
        validations,
    )
    _assert_dispatch_plan_chain(intent, plan_set)
    _assert_plan_materialization_chain(plan_set, materialization)

    validation_by_binding = {
        validation.materialization_binding_sha256: validation for validation in validations
    }
    binding_identities = tuple(
        binding.materialization_binding_sha256 for binding in materialization.bindings
    )
    if set(validation_by_binding) != set(binding_identities) or len(validation_by_binding) != len(
        validations
    ):
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "provider receipt validations must cover every materialization exactly once"
        )
    ordered_validations = tuple(validation_by_binding[identity] for identity in binding_identities)
    try:
        consumed_at = datetime.fromisoformat(intent.consumed_at)
    except (TypeError, ValueError) as exc:
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "provider receipt dispatch consumption time is invalid"
        ) from exc
    if consumed_at.tzinfo is None or consumed_at.utcoffset() is None:
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "provider receipt dispatch consumption time is not timezone-aware"
        )
    for binding, validation in zip(
        materialization.bindings,
        ordered_validations,
        strict=True,
    ):
        if (
            validation.plan_binding_sha256 != binding.plan_binding_sha256
            or validation.target_engine is not binding.target_engine
            or validation.projection_id != binding.projection_id
            or validation.target_ref != binding.target_ref
            or validation.provider_action != binding.provider_action
            or validation.provider_plan_sha256 != binding.provider_plan_sha256
            or validation.provider_idempotency_key != binding.provider_idempotency_key
            or validation.receipt_schema_id != binding.receipt_schema_id
        ):
            raise FederatedProjectionCompensationProviderReceiptSetError(
                "provider receipt validation differs from materialization binding"
            )
        if validation.observed_at < consumed_at:
            raise FederatedProjectionCompensationProviderReceiptSetError(
                "provider receipt observation predates authorization consumption"
            )

    values = {
        "tenant_id": intent.tenant_id,
        "run_id": intent.run_id,
        "proposal_sha256": intent.proposal_sha256,
        "candidate_sha256": intent.candidate_sha256,
        "source_snapshot_sha256": intent.source_snapshot_sha256,
        "dispatch_intent_sha256": intent.dispatch_intent_sha256,
        "execution_approval_case_ref": intent.execution_approval_case_ref,
        "review_approval_case_ref": intent.review_approval_case_ref,
        "execution_authorization_sha256": intent.execution_authorization_sha256,
        "review_binding_sha256": intent.review_binding_sha256,
        "plan_set_sha256": plan_set.plan_set_sha256,
        "adapter_resolution_sha256": plan_set.adapter_resolution_sha256,
        "adapter_id": plan_set.adapter_id,
        "adapter_semantic_version": plan_set.adapter_semantic_version,
        "adapter_sha256": plan_set.adapter_sha256,
        "implementation_artifact_sha256": plan_set.implementation_artifact_sha256,
        "materialization_set_sha256": materialization.materialization_set_sha256,
        "receipt_validations": ordered_validations,
        "receipt_count": len(ordered_validations),
        "receipt_set_state": ("complete_provider_receipts_pending_authority_admission"),
        "provider_receipts_complete": True,
        "authority_admission_performed": False,
        "authority_write_allowed": False,
        "checkpoint_write_allowed": False,
        "compensation_completion_allowed": False,
        "provider_invocation_performed_by_aggregator": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationProviderReceiptValidationSet.model_construct(
        **values,
        validation_set_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"validation_set_sha256"})
    return FederatedProjectionCompensationProviderReceiptValidationSet(
        **values,
        validation_set_sha256=_fingerprint(
            FederatedProjectionCompensationProviderReceiptValidationSet.schema_id,
            normalized,
            "validation_set_sha256",
        ),
    )


def build_federated_compensation_provider_receipt_validation_set_from_run(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    run_result: FederatedCompensationRunResult,
    validations: tuple[FederatedProjectionCompensationProviderReceiptValidation, ...],
) -> FederatedProjectionCompensationProviderReceiptValidationSet:
    """Bind a completed run to receipt validation before authority admission.

    Native adapters retain their receipt documents locally and independently
    produce receipt validations. This bridge only proves that those already
    validated receipt fingerprints match every sealed federated run position.
    It never invokes a Provider or writes any authority state.
    """

    intent, plan_set, materialization, validations = _validated_inputs(
        intent,
        plan_set,
        materialization,
        validations,
    )
    try:
        run_result = FederatedCompensationRunResult.model_validate(
            run_result.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "federated run result violates its sealed contract"
        ) from exc
    if (
        run_result.tenant_id != intent.tenant_id
        or run_result.run_id != intent.run_id
        or run_result.state
        is not FederatedCompensationRunState.COMPLETED_PENDING_AUTHORITY
        or not run_result.provider_receipts_complete
        or run_result.next_action != "admit_receipt_set"
    ):
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "federated run is not complete for receipt-set admission"
        )
    try:
        run_bindings = build_federated_compensation_run_bindings(
            plan_set,
            materialization,
        )
    except FederatedCompensationRunValidationError as exc:
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "federated run binding chain is invalid"
        ) from exc
    expected_positions = tuple(binding.position for binding in run_bindings)
    if (
        run_result.expected_positions != expected_positions
        or run_result.attempted_positions != expected_positions
        or run_result.unattempted_positions
        or len(run_result.steps) != len(run_bindings)
    ):
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "federated run positions differ from materialization"
        )
    validation_by_binding = {
        validation.materialization_binding_sha256: validation
        for validation in validations
    }
    expected_binding_hashes = {
        binding.materialization_binding_sha256 for binding in run_bindings
    }
    if (
        set(validation_by_binding) != expected_binding_hashes
        or len(validation_by_binding) != len(validations)
    ):
        raise FederatedProjectionCompensationProviderReceiptSetError(
            "provider receipt validations must cover every materialization exactly once"
        )
    for binding, step in zip(run_bindings, run_result.steps, strict=True):
        outcome = step.outcome
        validation = validation_by_binding[binding.materialization_binding_sha256]
        if (
            step.binding_sha256 != binding.binding_sha256
            or outcome.position != binding.position
            or outcome.source_plan_sha256 != binding.source_plan_sha256
            or outcome.provider_plan_sha256 != binding.provider_plan_sha256
            or outcome.provider_idempotency_key != binding.provider_idempotency_key
            or outcome.status
            not in {
                FederatedCompensationProviderOutcomeStatus.COMMITTED,
                FederatedCompensationProviderOutcomeStatus.REPLAYED,
            }
        ):
            raise FederatedProjectionCompensationProviderReceiptSetError(
                "federated run outcome differs from sealed materialization binding"
            )
        if (
            validation.plan_binding_sha256 != binding.plan_binding_sha256
            or validation.target_engine is not binding.target_engine
            or validation.projection_id != binding.projection_id
            or validation.target_ref != binding.target_ref
            or validation.provider_plan_sha256 != binding.provider_plan_sha256
            or validation.provider_idempotency_key != binding.provider_idempotency_key
            or validation.provider_receipt_sha256 != outcome.provider_receipt_sha256
        ):
            raise FederatedProjectionCompensationProviderReceiptSetError(
                "validated Provider receipt differs from federated run outcome"
            )
    return build_federated_compensation_provider_receipt_validation_set(
        intent,
        plan_set,
        materialization,
        validations,
    )


__all__ = [
    "FederatedProjectionCompensationProviderReceiptSetError",
    "FederatedProjectionCompensationProviderReceiptValidationSet",
    "build_federated_compensation_provider_receipt_validation_set",
    "build_federated_compensation_provider_receipt_validation_set_from_run",
]
