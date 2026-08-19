"""Execute one sealed federated compensation materialization in RDF/Fuseki.

The adapter is the RDF counterpart of the governed PostGIS compensation
adapter. It rebinds the complete dispatch/plan/materialization chain before
calling the existing plan-bound RDF executor. The target package is resolved
from the registered RDF target; callers never provide SPARQL, endpoints,
credentials, or arbitrary graph payloads.
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
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint
from .rdf_projection_executor import (
    RDFProjectionConfigurationError,
    RDFProjectionExecutionError,
    RDFProjectionRepairExecutor,
    RDFProjectionRepairReceipt,
    RDFProjectionTarget,
    RDFProjectionValidationError,
    rdf_projection_receipt_fingerprint,
)


class FederatedProjectionCompensationRDFAdapterError(RuntimeError):
    """Base error for the controlled RDF compensation adapter."""


class FederatedProjectionCompensationRDFAdapterConfigurationError(
    FederatedProjectionCompensationRDFAdapterError
):
    """The registered RDF execution channel is unavailable."""


class FederatedProjectionCompensationRDFAdapterValidationError(
    FederatedProjectionCompensationRDFAdapterError
):
    """The sealed chain, target, package, or receipt cannot be trusted."""


class FederatedProjectionCompensationRDFAdapterExecutionError(
    FederatedProjectionCompensationRDFAdapterError
):
    """The provider transaction failed or its outcome was not trustworthy."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def federated_compensation_rdf_payload_fingerprint(
    target: RDFProjectionTarget,
    action: Literal["checkpoint", "rebuild", "delete"],
) -> str:
    """Fingerprint the registered ontology package, without carrying its bytes."""

    try:
        target = RDFProjectionTarget.model_validate(target.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationRDFAdapterValidationError(
            "RDF compensation target violates the registered contract"
        ) from exc
    return canonical_json_fingerprint(
        {
            "schema": "gda.federated-projection-compensation-rdf-payload.v1",
            "target": {
                "tenant_id": target.tenant_id,
                "projection_id": target.projection_id,
                "target_ref": target.target_ref,
                "ontology_key": target.ontology_key,
                "semantic_version": target.semantic_version,
                "package_id": target.package_id,
                "package_content_sha256": target.package_content_sha256,
                "rdf_artifact_sha256": target.rdf_artifact_sha256,
                "expected_triple_count": target.expected_triple_count,
            },
            "action": action,
        }
    )


class FederatedProjectionCompensationRDFExecutionPlan(_FrozenModel):
    """Provider-local sealed plan exposing the executor's plan interface."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-rdf-execution-plan.v1"
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
    def _sealed_plan(self) -> FederatedProjectionCompensationRDFExecutionPlan:
        if self.source_plan.target_engine is not ProjectionEngine.RDF:
            raise ValueError("compensation RDF execution plan requires an RDF source plan")
        if self.source_plan.action not in {"checkpoint", "rebuild", "delete"}:
            raise ValueError("fail-closed source plans cannot reach the RDF adapter")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"execution_plan_sha256"}),
            "execution_plan_sha256",
        )
        if self.execution_plan_sha256 != expected:
            raise ValueError("compensation RDF execution plan fingerprint is invalid")
        return self


class FederatedProjectionCompensationRDFMutationRequest(_FrozenModel):
    """Exact structured request admitted for one RDF provider invocation."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-rdf-mutation-request.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    execution_plan: FederatedProjectionCompensationRDFExecutionPlan
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
    def _sealed_request(self) -> FederatedProjectionCompensationRDFMutationRequest:
        plan = self.execution_plan
        if self.tenant_id != plan.tenant_id or self.target_ref != plan.target_ref:
            raise ValueError("compensation RDF request target identity differs")
        if not self.dispatched_by.startswith("workload:"):
            raise ValueError("compensation RDF dispatch must use a workload identity")
        desired = plan.desired_state
        if plan.action == "rebuild" and desired.expected_target_content_sha256 is None:
            raise ValueError("compensation RDF request differs from desired target state")
        if (
            self.provider_execution_performed
            or self.checkpoint_authority_write_performed
            or self.compensation_completion_recorded
        ):
            raise ValueError("pending compensation RDF request cannot claim side effects")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("compensation RDF request fingerprint is invalid")
        return self


ProviderExecutionStatus = Literal[
    "provider_mutation_committed",
    "provider_idempotent_replay",
    "provider_checkpoint_recorded",
    "provider_delete_committed",
]


class FederatedProjectionCompensationRDFMutationResult(_FrozenModel):
    """Provider-native receipt evidence; no checkpoint completion is implied."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-rdf-mutation-result.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    request_sha256: Sha256
    execution_plan_sha256: Sha256
    materialization_binding_sha256: Sha256
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    receipt: RDFProjectionRepairReceipt
    provider_execution_status: ProviderExecutionStatus
    provider_execution_performed_by_adapter: Literal[True] = True
    provider_mutation_performed: bool
    provider_receipt_persisted_with_target_transaction: Literal[True] = True
    checkpoint_authority_write_performed_by_adapter: Literal[False] = False
    compensation_completion_recorded_by_adapter: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_result(self) -> FederatedProjectionCompensationRDFMutationResult:
        expected_status = {
            "completed": "provider_mutation_committed",
            "replayed": "provider_idempotent_replay",
            "checkpointed": "provider_checkpoint_recorded",
            "deleted": "provider_delete_committed",
        }[self.receipt.status]
        if self.provider_execution_status != expected_status:
            raise ValueError("compensation RDF result status differs from receipt")
        if self.provider_mutation_performed != (self.receipt.status in {"completed", "deleted"}):
            raise ValueError("compensation RDF mutation flag differs from receipt")
        if (
            self.receipt.tenant_id != self.tenant_id
            or self.receipt.plan_sha256 != self.provider_plan_sha256
            or self.receipt.idempotency_key != self.provider_idempotency_key
            or self.receipt.provider_commit_ref.get("provider") != "rdf_fuseki"
        ):
            raise ValueError("compensation RDF receipt differs from result")
        expected_receipt_sha256 = rdf_projection_receipt_fingerprint(
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
        )
        if self.receipt.provider_commit_ref.get("receipt_sha256") != expected_receipt_sha256:
            raise ValueError("compensation RDF provider receipt fingerprint is invalid")
        if (
            not self.provider_execution_performed_by_adapter
            or not self.provider_receipt_persisted_with_target_transaction
            or self.checkpoint_authority_write_performed_by_adapter
            or self.compensation_completion_recorded_by_adapter
        ):
            raise ValueError("compensation RDF result side-effect state is invalid")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("compensation RDF result fingerprint is invalid")
        return self


def _validated_inputs(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_plan: ProjectionRepairPlan,
    target: RDFProjectionTarget,
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    ProjectionRepairPlan,
    RDFProjectionTarget,
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
            RDFProjectionTarget.model_validate(target.model_dump(mode="python")),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationRDFAdapterValidationError(
            "compensation RDF adapter input violates a sealed contract"
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
        raise FederatedProjectionCompensationRDFAdapterValidationError(
            "compensation RDF dispatch, plan, or materialization identities differ"
        )
    source = next(
        (
            binding
            for binding in intent.plan_bindings
            if binding.plan_sha256 == source_plan.plan_sha256
        ),
        None,
    )
    plan_binding = next(
        (
            binding
            for binding in plan_set.plan_bindings
            if binding.source_plan_sha256 == source_plan.plan_sha256
        ),
        None,
    )
    if source is None or plan_binding is None:
        raise FederatedProjectionCompensationRDFAdapterValidationError(
            "source repair plan is absent from compensation dispatch or provider plan set"
        )
    materialized = next(
        (
            binding
            for binding in materialization.bindings
            if binding.position == plan_binding.position
        ),
        None,
    )
    desired = source_plan.desired_state
    if (
        materialized is None
        or source.position != plan_binding.position
        or source.source_resource_version_ref != desired.source_resource_version_ref
        or source.source_content_sha256 != desired.source_content_sha256
        or source.target_engine != ProjectionEngine.RDF.value
        or source.target_ref != source_plan.target_ref
        or source.sealed_action != source_plan.action
        or plan_binding.plan_binding_sha256 != materialized.plan_binding_sha256
        or plan_binding.target_engine is not ProjectionEngine.RDF
        or materialized.target_engine is not ProjectionEngine.RDF
        or plan_binding.target_ref != source_plan.target_ref
        or materialized.target_ref != source_plan.target_ref
        or materialized.projection_id != source_plan.projection_id
        or plan_binding.provider_action != source_plan.action
        or materialized.provider_action != source_plan.action
        or materialized.receipt_schema_id != "gda.rdf-projection-repair-receipt.v1"
        or desired.target_exists != materialized.expected_target_exists
        or desired.expected_target_content_sha256 != materialized.expected_target_content_sha256
        or desired.expected_row_count != materialized.expected_target_row_count
        or materialized.provider_idempotency_key != plan_binding.provider_idempotency_key
    ):
        raise FederatedProjectionCompensationRDFAdapterValidationError(
            "compensation RDF source plan differs from materialized provider plan"
        )
    return plan_binding, materialized


def build_federated_compensation_rdf_mutation_request(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_plan: ProjectionRepairPlan,
    target: RDFProjectionTarget,
    *,
    dispatched_by: str,
) -> FederatedProjectionCompensationRDFMutationRequest:
    """Rebind one RDF materialization before the first Provider side effect."""

    intent, plan_set, materialization, source_plan, target = _validated_inputs(
        intent, plan_set, materialization, source_plan, target
    )
    plan_binding, materialized = _matching_bindings(intent, plan_set, materialization, source_plan)
    if (
        target.tenant_id != source_plan.tenant_id
        or target.projection_id != source_plan.projection_id
        or target.target_ref != source_plan.target_ref
    ):
        raise FederatedProjectionCompensationRDFAdapterValidationError(
            "registered RDF target differs from the source repair plan"
        )
    payload_sha256 = federated_compensation_rdf_payload_fingerprint(target, source_plan.action)
    if payload_sha256 != materialized.payload_sha256:
        raise FederatedProjectionCompensationRDFAdapterValidationError(
            "private RDF payload differs from sealed materialization"
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
    normalized_plan = FederatedProjectionCompensationRDFExecutionPlan.model_construct(
        **plan_values, execution_plan_sha256="0" * 64
    ).model_dump(mode="json", exclude={"execution_plan_sha256"})
    execution_plan = FederatedProjectionCompensationRDFExecutionPlan(
        **plan_values,
        execution_plan_sha256=_fingerprint(
            FederatedProjectionCompensationRDFExecutionPlan.schema_id,
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
    normalized = FederatedProjectionCompensationRDFMutationRequest.model_construct(
        **values, request_sha256="0" * 64
    ).model_dump(mode="json", exclude={"request_sha256"})
    try:
        return FederatedProjectionCompensationRDFMutationRequest(
            **values,
            request_sha256=_fingerprint(
                FederatedProjectionCompensationRDFMutationRequest.schema_id,
                normalized,
                "request_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationRDFAdapterValidationError(
            "compensation RDF mutation request is invalid"
        ) from exc


def execute_federated_compensation_rdf_mutation(
    request: FederatedProjectionCompensationRDFMutationRequest,
    *,
    executor: RDFProjectionRepairExecutor,
) -> FederatedProjectionCompensationRDFMutationResult:
    """Invoke the governed RDF executor and return provider-native receipt evidence."""

    try:
        request = FederatedProjectionCompensationRDFMutationRequest.model_validate(
            request.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationRDFAdapterValidationError(
            "compensation RDF mutation request violates its sealed contract"
        ) from exc
    if not isinstance(executor, RDFProjectionRepairExecutor):
        raise FederatedProjectionCompensationRDFAdapterConfigurationError(
            "compensation RDF adapter requires the governed RDF executor"
        )
    plan = request.execution_plan
    try:
        registered_target = executor.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        registered_payload_sha256 = federated_compensation_rdf_payload_fingerprint(
            registered_target,
            plan.source_plan.action,
        )
    except RDFProjectionValidationError as exc:
        raise FederatedProjectionCompensationRDFAdapterValidationError(str(exc)) from exc
    if registered_payload_sha256 != plan.payload_sha256:
        raise FederatedProjectionCompensationRDFAdapterValidationError(
            "registered RDF package differs from the sealed compensation payload"
        )
    try:
        receipt = executor.execute(request.execution_plan)  # type: ignore[arg-type]
    except RDFProjectionValidationError as exc:
        raise FederatedProjectionCompensationRDFAdapterValidationError(str(exc)) from exc
    except RDFProjectionConfigurationError as exc:
        raise FederatedProjectionCompensationRDFAdapterConfigurationError(str(exc)) from exc
    except RDFProjectionExecutionError as exc:
        raise FederatedProjectionCompensationRDFAdapterExecutionError(str(exc)) from exc

    desired = plan.desired_state
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
    ):
        raise FederatedProjectionCompensationRDFAdapterExecutionError(
            "RDF provider receipt differs from the sealed compensation request"
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
        "provider_receipt_persisted_with_target_transaction": True,
        "checkpoint_authority_write_performed_by_adapter": False,
        "compensation_completion_recorded_by_adapter": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationRDFMutationResult.model_construct(
        **values, result_sha256="0" * 64
    ).model_dump(mode="json", exclude={"result_sha256"})
    try:
        return FederatedProjectionCompensationRDFMutationResult(
            **values,
            result_sha256=_fingerprint(
                FederatedProjectionCompensationRDFMutationResult.schema_id,
                normalized,
                "result_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationRDFAdapterExecutionError(
            "RDF compensation result is invalid"
        ) from exc


__all__ = [
    "FederatedProjectionCompensationRDFAdapterConfigurationError",
    "FederatedProjectionCompensationRDFAdapterError",
    "FederatedProjectionCompensationRDFAdapterExecutionError",
    "FederatedProjectionCompensationRDFAdapterValidationError",
    "FederatedProjectionCompensationRDFExecutionPlan",
    "FederatedProjectionCompensationRDFMutationRequest",
    "FederatedProjectionCompensationRDFMutationResult",
    "build_federated_compensation_rdf_mutation_request",
    "execute_federated_compensation_rdf_mutation",
    "federated_compensation_rdf_payload_fingerprint",
]
