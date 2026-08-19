"""Execute one sealed federated compensation materialization in an S3 object store.

The adapter rebinds dispatch, provider plan, deployment materialization, and
the registered Chongqing customer artifact before invoking the existing
plan-bound object executor. Endpoints, credentials, paths, and object bytes
remain private deployment material.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationBinding,
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanBinding,
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_consistency import (
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionRepairPlan,
    ProjectionTargetObservation,
)
from .object_projection_executor import (
    ObjectProjectionConfigurationError,
    ObjectProjectionExecutionError,
    ObjectProjectionRepairExecutor,
    ObjectProjectionRepairReceipt,
    ObjectProjectionTarget,
    ObjectProjectionValidationError,
    object_projection_receipt_fingerprint,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class FederatedProjectionCompensationObjectAdapterError(RuntimeError):
    """Base error for the controlled object-store compensation adapter."""


class FederatedProjectionCompensationObjectAdapterConfigurationError(
    FederatedProjectionCompensationObjectAdapterError
):
    """The registered object-store execution channel is unavailable."""


class FederatedProjectionCompensationObjectAdapterValidationError(
    FederatedProjectionCompensationObjectAdapterError
):
    """The sealed chain, target, artifact, or receipt cannot be trusted."""


class FederatedProjectionCompensationObjectAdapterExecutionError(
    FederatedProjectionCompensationObjectAdapterError
):
    """The provider mutation failed or returned untrustworthy evidence."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def federated_compensation_object_payload_fingerprint(
    target: ObjectProjectionTarget,
    action: Literal["checkpoint", "rebuild", "delete"],
) -> str:
    """Fingerprint the private target and artifact without carrying their values."""

    try:
        target = ObjectProjectionTarget.model_validate(target.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationObjectAdapterValidationError(
            "object compensation target violates the registered contract"
        ) from exc
    return canonical_json_fingerprint(
        {
            "schema": "gda.federated-projection-compensation-object-payload.v1",
            "registered_target": target.model_dump(mode="json"),
            "action": action,
        }
    )


class FederatedProjectionCompensationObjectExecutionPlan(_FrozenModel):
    """Provider-local sealed plan exposing the object executor plan interface."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-object-execution-plan.v1"
    )
    source_plan: ProjectionRepairPlan
    position: int = Field(ge=0, le=31)
    dispatch_intent_sha256: Sha256
    plan_set_sha256: Sha256
    plan_binding_sha256: Sha256
    materialization_set_sha256: Sha256
    materialization_binding_sha256: Sha256
    payload_sha256: Sha256
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    execution_plan_sha256: Sha256

    @property
    def tenant_id(self) -> str:
        return self.source_plan.tenant_id

    @property
    def projection_id(self) -> str:
        return self.source_plan.projection_id

    @property
    def target_engine(self) -> ProjectionEngine:
        return self.source_plan.target_engine

    @property
    def target_ref(self) -> str:
        return self.source_plan.target_ref

    @property
    def action(self) -> str:
        return self.source_plan.action

    @property
    def desired_state(self) -> ProjectionDesiredState:
        return self.source_plan.desired_state

    @property
    def observation(self) -> ProjectionTargetObservation:
        return self.source_plan.observation

    @property
    def previous_checkpoint_sha256(self) -> str | None:
        return self.source_plan.previous_checkpoint_sha256

    @property
    def next_checkpoint_version(self) -> int:
        return self.source_plan.next_checkpoint_version

    @property
    def plan_sha256(self) -> str:
        return self.provider_plan_sha256

    @property
    def plan_idempotency_key(self) -> str:
        return self.provider_idempotency_key

    @model_validator(mode="after")
    def _sealed_plan(self) -> FederatedProjectionCompensationObjectExecutionPlan:
        if self.source_plan.target_engine is not ProjectionEngine.OBJECT_STORE:
            raise ValueError("compensation object plan requires an object-store source plan")
        if self.source_plan.action not in {"checkpoint", "rebuild", "delete"}:
            raise ValueError("fail-closed source plans cannot reach the object adapter")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"execution_plan_sha256"}),
            "execution_plan_sha256",
        )
        if self.execution_plan_sha256 != expected:
            raise ValueError("compensation object execution plan fingerprint is invalid")
        return self


class FederatedProjectionCompensationObjectMutationRequest(_FrozenModel):
    """Exact structured request admitted for one object-store invocation."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-object-mutation-request.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    execution_plan: FederatedProjectionCompensationObjectExecutionPlan
    target_ref: NonEmptyText
    dispatched_by: NonEmptyText
    request_state: Literal["authorized_materialization_pending_provider_execution"] = (
        "authorized_materialization_pending_provider_execution"
    )
    provider_execution_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    request_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_request(self) -> FederatedProjectionCompensationObjectMutationRequest:
        plan = self.execution_plan
        if self.tenant_id != plan.tenant_id or self.target_ref != plan.target_ref:
            raise ValueError("compensation object request target identity differs")
        if not self.dispatched_by.startswith("workload:"):
            raise ValueError("compensation object dispatch must use a workload identity")
        if plan.action == "rebuild" and plan.desired_state.expected_target_content_sha256 is None:
            raise ValueError("compensation object request differs from desired target state")
        if (
            self.provider_execution_performed
            or self.checkpoint_authority_write_performed
            or self.compensation_completion_recorded
        ):
            raise ValueError("pending compensation object request cannot claim side effects")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("compensation object request fingerprint is invalid")
        return self


ProviderExecutionStatus = Literal[
    "provider_mutation_committed",
    "provider_idempotent_replay",
    "provider_checkpoint_recorded",
    "provider_delete_committed",
]


class FederatedProjectionCompensationObjectMutationResult(_FrozenModel):
    """Provider-native version evidence; no checkpoint completion is implied."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-object-mutation-result.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    request_sha256: Sha256
    execution_plan_sha256: Sha256
    materialization_binding_sha256: Sha256
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    receipt: ObjectProjectionRepairReceipt
    provider_execution_status: ProviderExecutionStatus
    provider_execution_performed_by_adapter: Literal[True] = True
    provider_mutation_performed: bool
    provider_receipt_evidence_validated: Literal[True] = True
    checkpoint_authority_write_performed_by_adapter: Literal[False] = False
    compensation_completion_recorded_by_adapter: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_result(self) -> FederatedProjectionCompensationObjectMutationResult:
        expected_status = {
            "completed": "provider_mutation_committed",
            "replayed": "provider_idempotent_replay",
            "checkpointed": "provider_checkpoint_recorded",
            "deleted": "provider_delete_committed",
        }[self.receipt.status]
        if self.provider_execution_status != expected_status:
            raise ValueError("compensation object result status differs from receipt")
        if self.provider_mutation_performed != (self.receipt.status in {"completed", "deleted"}):
            raise ValueError("compensation object mutation flag differs from receipt")
        if (
            self.receipt.tenant_id != self.tenant_id
            or self.receipt.plan_sha256 != self.provider_plan_sha256
            or self.receipt.idempotency_key != self.provider_idempotency_key
            or self.receipt.provider_commit_ref.get("provider") != "s3_object_store"
        ):
            raise ValueError("compensation object receipt differs from result")
        expected_receipt_sha256 = object_projection_receipt_fingerprint(
            tenant_id=self.receipt.tenant_id,
            projection_id=self.receipt.projection_id,
            target_ref=self.receipt.target_ref,
            action=self.receipt.action,
            plan_sha256=self.receipt.plan_sha256,
            idempotency_key=self.receipt.idempotency_key,
            provider_commit_ref=self.receipt.provider_commit_ref,
            target_exists=self.receipt.target_exists,
            target_content_sha256=self.receipt.target_content_sha256,
            target_row_count=self.receipt.target_row_count,
            target_size_bytes=self.receipt.target_size_bytes,
        )
        if self.receipt.provider_commit_ref.get("receipt_sha256") != expected_receipt_sha256:
            raise ValueError("compensation object provider receipt fingerprint is invalid")
        if (
            not self.provider_execution_performed_by_adapter
            or not self.provider_receipt_evidence_validated
            or self.checkpoint_authority_write_performed_by_adapter
            or self.compensation_completion_recorded_by_adapter
        ):
            raise ValueError("compensation object result side-effect state is invalid")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("compensation object result fingerprint is invalid")
        return self


def _validated_inputs(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_plan: ProjectionRepairPlan,
    target: ObjectProjectionTarget,
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    ProjectionRepairPlan,
    ObjectProjectionTarget,
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
            ProjectionRepairPlan.model_validate(source_plan.model_dump(mode="python")),
            ObjectProjectionTarget.model_validate(target.model_dump(mode="python")),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationObjectAdapterValidationError(
            "compensation object adapter input violates a sealed contract"
        ) from exc


def _matching_bindings(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_plan: ProjectionRepairPlan,
) -> tuple[
    FederatedProjectionCompensationProviderPlanBinding,
    FederatedProjectionCompensationProviderMaterializationBinding,
]:
    if (
        plan_set.tenant_id != intent.tenant_id
        or plan_set.run_id != intent.run_id
        or plan_set.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or materialization.tenant_id != intent.tenant_id
        or materialization.run_id != intent.run_id
        or materialization.plan_set_sha256 != plan_set.plan_set_sha256
        or materialization.adapter_id != plan_set.adapter_id
        or materialization.adapter_semantic_version != plan_set.adapter_semantic_version
        or materialization.adapter_sha256 != plan_set.adapter_sha256
        or materialization.implementation_artifact_sha256 != plan_set.implementation_artifact_sha256
    ):
        raise FederatedProjectionCompensationObjectAdapterValidationError(
            "compensation object dispatch, plan, or materialization identities differ"
        )
    source = next(
        (item for item in intent.plan_bindings if item.plan_sha256 == source_plan.plan_sha256),
        None,
    )
    plan_binding = next(
        (
            item
            for item in plan_set.plan_bindings
            if item.source_plan_sha256 == source_plan.plan_sha256
        ),
        None,
    )
    if source is None or plan_binding is None:
        raise FederatedProjectionCompensationObjectAdapterValidationError(
            "source repair plan is absent from compensation dispatch or provider plan set"
        )
    materialized = next(
        (item for item in materialization.bindings if item.position == plan_binding.position),
        None,
    )
    desired = source_plan.desired_state
    if (
        materialized is None
        or source.position != plan_binding.position
        or source.source_resource_version_ref != desired.source_resource_version_ref
        or source.source_content_sha256 != desired.source_content_sha256
        or source.target_engine != ProjectionEngine.OBJECT_STORE.value
        or source.target_ref != source_plan.target_ref
        or source.sealed_action != source_plan.action
        or plan_binding.plan_binding_sha256 != materialized.plan_binding_sha256
        or plan_binding.target_engine is not ProjectionEngine.OBJECT_STORE
        or materialized.target_engine is not ProjectionEngine.OBJECT_STORE
        or plan_binding.target_ref != source_plan.target_ref
        or materialized.target_ref != source_plan.target_ref
        or materialized.projection_id != source_plan.projection_id
        or plan_binding.provider_action != source_plan.action
        or materialized.provider_action != source_plan.action
        or materialized.receipt_schema_id != "gda.object-projection-repair-receipt.v1"
        or desired.target_exists != materialized.expected_target_exists
        or desired.expected_target_content_sha256
        != materialized.expected_target_content_sha256
        or desired.expected_row_count != materialized.expected_target_row_count
        or materialized.provider_idempotency_key != plan_binding.provider_idempotency_key
    ):
        raise FederatedProjectionCompensationObjectAdapterValidationError(
            "compensation object source plan differs from materialized provider plan"
        )
    return plan_binding, materialized


def build_federated_compensation_object_mutation_request(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_plan: ProjectionRepairPlan,
    target: ObjectProjectionTarget,
    *,
    dispatched_by: str,
) -> FederatedProjectionCompensationObjectMutationRequest:
    """Rebind one object materialization before the first provider side effect."""

    intent, plan_set, materialization, source_plan, target = _validated_inputs(
        intent, plan_set, materialization, source_plan, target
    )
    plan_binding, materialized = _matching_bindings(
        intent, plan_set, materialization, source_plan
    )
    if (
        target.tenant_id != source_plan.tenant_id
        or target.projection_id != source_plan.projection_id
        or target.target_ref != source_plan.target_ref
    ):
        raise FederatedProjectionCompensationObjectAdapterValidationError(
            "registered object target differs from the source repair plan"
        )
    payload_sha256 = federated_compensation_object_payload_fingerprint(
        target, source_plan.action
    )
    if payload_sha256 != materialized.payload_sha256:
        raise FederatedProjectionCompensationObjectAdapterValidationError(
            "private object payload differs from sealed materialization"
        )
    plan_values = {
        "source_plan": source_plan,
        "position": plan_binding.position,
        "dispatch_intent_sha256": intent.dispatch_intent_sha256,
        "plan_set_sha256": plan_set.plan_set_sha256,
        "plan_binding_sha256": plan_binding.plan_binding_sha256,
        "materialization_set_sha256": materialization.materialization_set_sha256,
        "materialization_binding_sha256": materialized.materialization_binding_sha256,
        "payload_sha256": payload_sha256,
        "provider_plan_sha256": materialized.provider_plan_sha256,
        "provider_idempotency_key": materialized.provider_idempotency_key,
    }
    normalized_plan = FederatedProjectionCompensationObjectExecutionPlan.model_construct(
        **plan_values, execution_plan_sha256="0" * 64
    ).model_dump(mode="json", exclude={"execution_plan_sha256"})
    execution_plan = FederatedProjectionCompensationObjectExecutionPlan(
        **plan_values,
        execution_plan_sha256=_fingerprint(
            FederatedProjectionCompensationObjectExecutionPlan.schema_id,
            normalized_plan,
            "execution_plan_sha256",
        ),
    )
    values = {
        "tenant_id": intent.tenant_id,
        "run_id": intent.run_id,
        "execution_plan": execution_plan,
        "target_ref": target.target_ref,
        "dispatched_by": dispatched_by,
        "request_state": "authorized_materialization_pending_provider_execution",
        "provider_execution_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationObjectMutationRequest.model_construct(
        **values, request_sha256="0" * 64
    ).model_dump(mode="json", exclude={"request_sha256"})
    try:
        return FederatedProjectionCompensationObjectMutationRequest(
            **values,
            request_sha256=_fingerprint(
                FederatedProjectionCompensationObjectMutationRequest.schema_id,
                normalized,
                "request_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationObjectAdapterValidationError(
            "compensation object mutation request is invalid"
        ) from exc


def execute_federated_compensation_object_mutation(
    request: FederatedProjectionCompensationObjectMutationRequest,
    *,
    executor: ObjectProjectionRepairExecutor,
) -> FederatedProjectionCompensationObjectMutationResult:
    """Invoke the governed object executor and return immutable version evidence."""

    try:
        request = FederatedProjectionCompensationObjectMutationRequest.model_validate(
            request.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationObjectAdapterValidationError(
            "compensation object mutation request violates its sealed contract"
        ) from exc
    if not isinstance(executor, ObjectProjectionRepairExecutor):
        raise FederatedProjectionCompensationObjectAdapterConfigurationError(
            "compensation object adapter requires the governed object executor"
        )
    plan = request.execution_plan
    try:
        registered_target = executor.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        registered_payload_sha256 = federated_compensation_object_payload_fingerprint(
            registered_target, plan.source_plan.action
        )
    except ObjectProjectionValidationError as exc:
        raise FederatedProjectionCompensationObjectAdapterValidationError(str(exc)) from exc
    if registered_payload_sha256 != plan.payload_sha256:
        raise FederatedProjectionCompensationObjectAdapterValidationError(
            "registered object artifact differs from the sealed compensation payload"
        )
    try:
        receipt = executor.execute(request.execution_plan)  # type: ignore[arg-type]
    except ObjectProjectionValidationError as exc:
        raise FederatedProjectionCompensationObjectAdapterValidationError(str(exc)) from exc
    except ObjectProjectionConfigurationError as exc:
        raise FederatedProjectionCompensationObjectAdapterConfigurationError(str(exc)) from exc
    except ObjectProjectionExecutionError as exc:
        raise FederatedProjectionCompensationObjectAdapterExecutionError(str(exc)) from exc

    desired = plan.desired_state
    expected_size = registered_target.artifact_size_bytes if desired.target_exists else 0
    if (
        receipt.tenant_id != request.tenant_id
        or receipt.projection_id != plan.projection_id
        or receipt.target_ref != plan.target_ref
        or receipt.action != plan.action
        or receipt.plan_sha256 != plan.provider_plan_sha256
        or receipt.idempotency_key != plan.provider_idempotency_key
        or receipt.target_exists != desired.target_exists
        or receipt.target_content_sha256 != desired.expected_target_content_sha256
        or receipt.target_row_count != desired.expected_row_count
        or receipt.target_size_bytes != expected_size
    ):
        raise FederatedProjectionCompensationObjectAdapterExecutionError(
            "object provider receipt differs from the sealed compensation request"
        )
    execution_status: ProviderExecutionStatus = {
        "completed": "provider_mutation_committed",
        "replayed": "provider_idempotent_replay",
        "checkpointed": "provider_checkpoint_recorded",
        "deleted": "provider_delete_committed",
    }[receipt.status]
    values = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "position": plan.position,
        "request_sha256": request.request_sha256,
        "execution_plan_sha256": plan.execution_plan_sha256,
        "materialization_binding_sha256": plan.materialization_binding_sha256,
        "provider_plan_sha256": plan.provider_plan_sha256,
        "provider_idempotency_key": plan.provider_idempotency_key,
        "receipt": receipt,
        "provider_execution_status": execution_status,
        "provider_execution_performed_by_adapter": True,
        "provider_mutation_performed": receipt.status in {"completed", "deleted"},
        "provider_receipt_evidence_validated": True,
        "checkpoint_authority_write_performed_by_adapter": False,
        "compensation_completion_recorded_by_adapter": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationObjectMutationResult.model_construct(
        **values, result_sha256="0" * 64
    ).model_dump(mode="json", exclude={"result_sha256"})
    try:
        return FederatedProjectionCompensationObjectMutationResult(
            **values,
            result_sha256=_fingerprint(
                FederatedProjectionCompensationObjectMutationResult.schema_id,
                normalized,
                "result_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationObjectAdapterExecutionError(
            "object compensation result is invalid"
        ) from exc


__all__ = [
    "FederatedProjectionCompensationObjectAdapterConfigurationError",
    "FederatedProjectionCompensationObjectAdapterError",
    "FederatedProjectionCompensationObjectAdapterExecutionError",
    "FederatedProjectionCompensationObjectAdapterValidationError",
    "FederatedProjectionCompensationObjectExecutionPlan",
    "FederatedProjectionCompensationObjectMutationRequest",
    "FederatedProjectionCompensationObjectMutationResult",
    "build_federated_compensation_object_mutation_request",
    "execute_federated_compensation_object_mutation",
    "federated_compensation_object_payload_fingerprint",
]
