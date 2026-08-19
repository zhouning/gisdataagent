"""Execute one sealed federated compensation materialization in PostGIS.

This adapter is the explicit bridge between the customer-rule compensation
control plane and the existing plan-bound PostGIS executor. It accepts only a
fully rebound dispatch/plan/materialization chain plus structured rows for an
allowlisted target. It never accepts SQL, credentials, or an endpoint, and it
does not write checkpoint or compensation-completion authorities.
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
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)
from .postgis_projection_executor import (
    PostGISProjectionConfigurationError,
    PostGISProjectionExecutionError,
    PostGISProjectionRepairExecutor,
    PostGISProjectionRepairReceipt,
    PostGISProjectionTarget,
    PostGISProjectionValidationError,
    postgis_projection_receipt_fingerprint,
    projection_rows_fingerprint,
)


class FederatedProjectionCompensationPostGISAdapterError(RuntimeError):
    """Base error for the controlled PostGIS compensation adapter."""


class FederatedProjectionCompensationPostGISAdapterConfigurationError(
    FederatedProjectionCompensationPostGISAdapterError
):
    """The registered PostGIS execution channel is unavailable."""


class FederatedProjectionCompensationPostGISAdapterValidationError(
    FederatedProjectionCompensationPostGISAdapterError
):
    """The sealed chain, target, payload, or receipt cannot be trusted."""


class FederatedProjectionCompensationPostGISAdapterExecutionError(
    FederatedProjectionCompensationPostGISAdapterError
):
    """The provider transaction failed or its outcome was not trustworthy."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def federated_compensation_postgis_payload_fingerprint(
    target: PostGISProjectionTarget,
    action: Literal["checkpoint", "rebuild", "delete"],
    rows: tuple[dict[str, Any], ...],
) -> str:
    """Fingerprint private structured material without exposing SQL or secrets."""

    target = PostGISProjectionTarget.model_validate(target.model_dump(mode="python"))
    if action in {"checkpoint", "delete"} and rows:
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            f"{action} compensation material must not contain rows"
        )
    try:
        rows_sha256 = projection_rows_fingerprint(target, rows)
    except PostGISProjectionValidationError as exc:
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            "PostGIS compensation rows violate the registered target"
        ) from exc
    return canonical_json_fingerprint(
        {
            "schema": "gda.federated-projection-compensation-postgis-payload.v1",
            "target": target.model_dump(mode="json"),
            "action": action,
            "row_count": len(rows),
            "rows_sha256": rows_sha256,
        }
    )


class FederatedProjectionCompensationPostGISExecutionPlan(_FrozenModel):
    """Provider-local sealed plan with the interface required by the executor."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-postgis-execution-plan.v1"
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
    def _sealed_plan(
        self,
    ) -> FederatedProjectionCompensationPostGISExecutionPlan:
        if self.source_plan.target_engine is not ProjectionEngine.POSTGIS:
            raise ValueError("compensation PostGIS execution plan requires a postgis source plan")
        if self.source_plan.action not in {"checkpoint", "rebuild", "delete"}:
            raise ValueError("fail-closed source plans cannot reach the PostGIS adapter")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"execution_plan_sha256"}),
            "execution_plan_sha256",
        )
        if self.execution_plan_sha256 != expected:
            raise ValueError("compensation PostGIS execution plan fingerprint is invalid")
        return self


class FederatedProjectionCompensationPostGISMutationRequest(_FrozenModel):
    """Exact structured request admitted for one PostGIS provider invocation."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-postgis-mutation-request.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    execution_plan: FederatedProjectionCompensationPostGISExecutionPlan
    target: PostGISProjectionTarget
    rows: tuple[dict[str, Any], ...] = Field(default=(), max_length=100_000)
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
    def _sealed_request(
        self,
    ) -> FederatedProjectionCompensationPostGISMutationRequest:
        plan = self.execution_plan
        if (
            self.tenant_id != plan.tenant_id
            or self.target.tenant_id != plan.tenant_id
            or self.target.projection_id != plan.projection_id
            or self.target.target_ref != plan.target_ref
        ):
            raise ValueError("compensation PostGIS request target identity differs")
        if not self.dispatched_by.startswith("workload:"):
            raise ValueError("compensation PostGIS dispatch must use a workload identity")
        payload_sha256 = federated_compensation_postgis_payload_fingerprint(
            self.target,
            plan.source_plan.action,
            self.rows,
        )
        if payload_sha256 != plan.payload_sha256:
            raise ValueError("compensation PostGIS request payload differs from materialization")
        desired = plan.desired_state
        if plan.action == "rebuild":
            try:
                rows_sha256 = projection_rows_fingerprint(self.target, self.rows)
            except PostGISProjectionValidationError as exc:
                raise ValueError("compensation PostGIS request rows are invalid") from exc
            if (
                len(self.rows) != desired.expected_row_count
                or rows_sha256 != desired.expected_target_content_sha256
            ):
                raise ValueError("compensation PostGIS rows differ from desired target state")
        if (
            self.provider_execution_performed
            or self.checkpoint_authority_write_performed
            or self.compensation_completion_recorded
        ):
            raise ValueError("pending compensation PostGIS request cannot claim side effects")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("compensation PostGIS request fingerprint is invalid")
        return self


ProviderExecutionStatus = Literal[
    "provider_mutation_committed",
    "provider_idempotent_replay",
    "provider_checkpoint_recorded",
    "provider_delete_committed",
]


class FederatedProjectionCompensationPostGISMutationResult(_FrozenModel):
    """Provider-native receipt evidence; no checkpoint completion is implied."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-postgis-mutation-result.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    request_sha256: Sha256
    execution_plan_sha256: Sha256
    materialization_binding_sha256: Sha256
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    receipt: PostGISProjectionRepairReceipt
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
    def _sealed_result(
        self,
    ) -> FederatedProjectionCompensationPostGISMutationResult:
        expected_status = {
            "completed": "provider_mutation_committed",
            "replayed": "provider_idempotent_replay",
            "checkpointed": "provider_checkpoint_recorded",
            "deleted": "provider_delete_committed",
        }[self.receipt.status]
        if self.provider_execution_status != expected_status:
            raise ValueError("compensation PostGIS result status differs from receipt")
        if self.provider_mutation_performed != (self.receipt.status in {"completed", "deleted"}):
            raise ValueError("compensation PostGIS mutation flag differs from receipt")
        if (
            self.receipt.tenant_id != self.tenant_id
            or self.receipt.plan_sha256 != self.provider_plan_sha256
            or self.receipt.idempotency_key != self.provider_idempotency_key
            or self.receipt.provider_commit_ref.get("provider") != "postgis"
        ):
            raise ValueError("compensation PostGIS receipt differs from result")
        expected_receipt_sha256 = postgis_projection_receipt_fingerprint(
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
            raise ValueError("compensation PostGIS provider receipt fingerprint is invalid")
        if (
            not self.provider_execution_performed_by_adapter
            or not self.provider_receipt_persisted_with_target_transaction
            or self.checkpoint_authority_write_performed_by_adapter
            or self.compensation_completion_recorded_by_adapter
        ):
            raise ValueError("compensation PostGIS result side-effect state is invalid")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("compensation PostGIS result fingerprint is invalid")
        return self


def _validated_inputs(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_plan: ProjectionRepairPlan,
    target: PostGISProjectionTarget,
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    ProjectionRepairPlan,
    PostGISProjectionTarget,
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
            PostGISProjectionTarget.model_validate(target.model_dump(mode="python")),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            "compensation PostGIS adapter input violates a sealed contract"
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
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            "compensation PostGIS dispatch, plan, or materialization identities differ"
        )
    source = next(
        (
            binding
            for binding in intent.plan_bindings
            if binding.plan_sha256 == source_plan.plan_sha256
        ),
        None,
    )
    if source is None:
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            "source repair plan is absent from compensation dispatch"
        )
    plan_binding = next(
        (
            binding
            for binding in plan_set.plan_bindings
            if binding.source_plan_sha256 == source_plan.plan_sha256
        ),
        None,
    )
    if plan_binding is None:
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            "source repair plan is absent from provider plan set"
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
        or source.target_engine != ProjectionEngine.POSTGIS.value
        or source.target_ref != source_plan.target_ref
        or source.sealed_action != source_plan.action
        or plan_binding.plan_binding_sha256 != materialized.plan_binding_sha256
        or plan_binding.target_engine is not ProjectionEngine.POSTGIS
        or materialized.target_engine is not ProjectionEngine.POSTGIS
        or plan_binding.target_ref != source_plan.target_ref
        or materialized.target_ref != source_plan.target_ref
        or materialized.projection_id != source_plan.projection_id
        or plan_binding.provider_action != source_plan.action
        or materialized.provider_action != source_plan.action
        or materialized.receipt_schema_id != "gda.postgis-projection-repair-receipt.v1"
        or desired.target_exists != materialized.expected_target_exists
        or desired.expected_target_content_sha256 != materialized.expected_target_content_sha256
        or desired.expected_row_count != materialized.expected_target_row_count
        or materialized.provider_idempotency_key != plan_binding.provider_idempotency_key
    ):
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            "compensation PostGIS source plan differs from materialized provider plan"
        )
    return plan_binding, materialized


def build_federated_compensation_postgis_mutation_request(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_plan: ProjectionRepairPlan,
    target: PostGISProjectionTarget,
    rows: tuple[dict[str, Any], ...],
    *,
    dispatched_by: str,
) -> FederatedProjectionCompensationPostGISMutationRequest:
    """Rebind one PostGIS materialization before the first Provider side effect."""

    intent, plan_set, materialization, source_plan, target = _validated_inputs(
        intent,
        plan_set,
        materialization,
        source_plan,
        target,
    )
    plan_binding, materialized = _matching_bindings(
        intent,
        plan_set,
        materialization,
        source_plan,
    )
    if (
        target.tenant_id != source_plan.tenant_id
        or target.projection_id != source_plan.projection_id
        or target.target_ref != source_plan.target_ref
    ):
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            "registered PostGIS target differs from the source repair plan"
        )
    payload_sha256 = federated_compensation_postgis_payload_fingerprint(
        target,
        source_plan.action,
        rows,
    )
    if payload_sha256 != materialized.payload_sha256:
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            "private PostGIS payload differs from sealed materialization"
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
    normalized_plan = FederatedProjectionCompensationPostGISExecutionPlan.model_construct(
        **plan_values,
        execution_plan_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"execution_plan_sha256"})
    execution_plan = FederatedProjectionCompensationPostGISExecutionPlan(
        **plan_values,
        execution_plan_sha256=_fingerprint(
            FederatedProjectionCompensationPostGISExecutionPlan.schema_id,
            normalized_plan,
            "execution_plan_sha256",
        ),
    )
    values = {
        "tenant_id": intent.tenant_id,
        "run_id": intent.run_id,
        "execution_plan": execution_plan,
        "target": target,
        "rows": rows,
        "dispatched_by": dispatched_by,
        "request_state": "authorized_materialization_pending_provider_execution",
        "provider_execution_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationPostGISMutationRequest.model_construct(
        **values,
        request_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"request_sha256"})
    try:
        return FederatedProjectionCompensationPostGISMutationRequest(
            **values,
            request_sha256=_fingerprint(
                FederatedProjectionCompensationPostGISMutationRequest.schema_id,
                normalized,
                "request_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            "compensation PostGIS mutation request is invalid"
        ) from exc


def execute_federated_compensation_postgis_mutation(
    request: FederatedProjectionCompensationPostGISMutationRequest,
    *,
    executor: PostGISProjectionRepairExecutor,
) -> FederatedProjectionCompensationPostGISMutationResult:
    """Invoke the registered executor and return provider-native receipt evidence."""

    try:
        request = FederatedProjectionCompensationPostGISMutationRequest.model_validate(
            request.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationPostGISAdapterValidationError(
            "compensation PostGIS mutation request violates its sealed contract"
        ) from exc
    if not isinstance(executor, PostGISProjectionRepairExecutor):
        raise FederatedProjectionCompensationPostGISAdapterConfigurationError(
            "compensation PostGIS adapter requires the governed PostGIS executor"
        )
    try:
        receipt = executor.execute(
            request.execution_plan,  # type: ignore[arg-type]
            rows=request.rows,
        )
    except PostGISProjectionValidationError as exc:
        raise FederatedProjectionCompensationPostGISAdapterValidationError(str(exc)) from exc
    except PostGISProjectionConfigurationError as exc:
        raise FederatedProjectionCompensationPostGISAdapterConfigurationError(str(exc)) from exc
    except PostGISProjectionExecutionError as exc:
        raise FederatedProjectionCompensationPostGISAdapterExecutionError(str(exc)) from exc

    plan = request.execution_plan
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
        raise FederatedProjectionCompensationPostGISAdapterExecutionError(
            "PostGIS provider receipt differs from the sealed compensation request"
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
    normalized = FederatedProjectionCompensationPostGISMutationResult.model_construct(
        **values,
        result_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"result_sha256"})
    try:
        return FederatedProjectionCompensationPostGISMutationResult(
            **values,
            result_sha256=_fingerprint(
                FederatedProjectionCompensationPostGISMutationResult.schema_id,
                normalized,
                "result_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationPostGISAdapterExecutionError(
            "PostGIS compensation result is invalid"
        ) from exc


__all__ = [
    "FederatedProjectionCompensationPostGISAdapterConfigurationError",
    "FederatedProjectionCompensationPostGISAdapterError",
    "FederatedProjectionCompensationPostGISAdapterExecutionError",
    "FederatedProjectionCompensationPostGISAdapterValidationError",
    "FederatedProjectionCompensationPostGISExecutionPlan",
    "FederatedProjectionCompensationPostGISMutationRequest",
    "FederatedProjectionCompensationPostGISMutationResult",
    "build_federated_compensation_postgis_mutation_request",
    "execute_federated_compensation_postgis_mutation",
    "federated_compensation_postgis_payload_fingerprint",
]
