"""Record one sealed Chongqing five-Provider run in checkpoint authorities.

Provider mutations have already completed before this module is called.  The
orchestrator validates the 5/5 receipt set, records five checkpoints in order,
and records compensation completion only after every checkpoint is current.
It is deliberately not a cross-store transaction and never invokes a Provider.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_authority import PostgresProjectionCheckpointAuthority
from .cross_store_projection_compensation_checkpoint_admission import (
    FederatedProjectionCompensationCheckpointAdmissionRequest,
    build_federated_compensation_checkpoint_admission_request,
)
from .cross_store_projection_compensation_checkpoint_authority_read import (
    FederatedProjectionCompensationCheckpointAuthorityReadPreview,
    build_federated_compensation_checkpoint_authority_read_preview,
)
from .cross_store_projection_compensation_checkpoint_candidate import (
    FederatedProjectionCompensationCheckpointPredecessor,
    build_federated_compensation_checkpoint_candidate_set,
)
from .cross_store_projection_compensation_checkpoint_write_intent import (
    FederatedProjectionCompensationCheckpointWriteIntentSet,
    build_federated_compensation_checkpoint_write_intent_set,
)
from .cross_store_projection_compensation_checkpoint_write_request import (
    FederatedProjectionCompensationCheckpointWriteRequestSet,
    build_federated_compensation_checkpoint_write_request_set,
)
from .cross_store_projection_compensation_checkpoint_writer import (
    FederatedProjectionCompensationCheckpointAuthorityRecordSet,
    ProjectionCheckpointAuthorityWriter,
    record_federated_compensation_checkpoint_write_request_set,
)
from .cross_store_projection_compensation_chongqing_five_provider_execution import (
    ChongqingFederatedCompensationFiveProviderExecutionResult,
    ChongqingFederatedCompensationFiveProviderRequestBundle,
)
from .cross_store_projection_compensation_completion_authority import (
    FederatedProjectionCompensationCompletionReceipt,
    FederatedProjectionCompensationCompletionRequest,
    FederatedProjectionCompensationCompletionWriteResult,
    PostgresFederatedProjectionCompensationCompletionAuthority,
    build_federated_projection_compensation_completion_request,
)
from .cross_store_projection_compensation_federated_receipt_execution import (
    FederatedCompensationRegisteredReceiptExecutionState,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_consistency import (
    ProjectionEngine,
    ProjectionRepairPlan,
    ProjectionTargetObservation,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class ChongqingFederatedCompensationFiveProviderAuthorityError(RuntimeError):
    """A five-Provider result cannot safely pass the authority boundary."""


class ChongqingFederatedCompensationFiveProviderAuthorityValidationError(
    ChongqingFederatedCompensationFiveProviderAuthorityError,
):
    """The execution, request, plan, observation, or authority evidence drifted."""


class CompensationCompletionAuthority(Protocol):
    def record(
        self,
        request: FederatedProjectionCompensationCompletionRequest,
    ) -> FederatedProjectionCompensationCompletionWriteResult: ...

    def current(
        self,
        run_id: str,
    ) -> FederatedProjectionCompensationCompletionReceipt | None: ...


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


AuthorityState = Literal[
    "checkpoint_authority_records_incomplete_pending_reconciliation",
    "five_provider_compensation_completion_recorded",
    "five_provider_compensation_completion_reused",
]


class ChongqingFederatedCompensationFiveProviderAuthorityResult(_FrozenModel):
    """Durable checkpoint/completion outcome for one five-Provider execution."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-five-provider-authority-result.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    execution_result_sha256: Sha256
    request_bundle_sha256: Sha256
    receipt_validation_set_sha256: Sha256
    admission_request: FederatedProjectionCompensationCheckpointAdmissionRequest
    authority_read_preview: FederatedProjectionCompensationCheckpointAuthorityReadPreview
    write_intent_set: FederatedProjectionCompensationCheckpointWriteIntentSet
    write_request_set: FederatedProjectionCompensationCheckpointWriteRequestSet
    authority_record_set: FederatedProjectionCompensationCheckpointAuthorityRecordSet
    completion_request: FederatedProjectionCompensationCompletionRequest | None = None
    completion_receipt: FederatedProjectionCompensationCompletionReceipt | None = None
    completion_created: bool | None = None
    authority_state: AuthorityState
    checkpoint_count_recorded: int = Field(ge=0, le=5)
    authority_admission_performed: Literal[True] = True
    checkpoint_authority_write_performed: Literal[True] = True
    completion_authority_record_invoked: bool
    compensation_completion_recorded: bool
    provider_execution_performed_by_authority: Literal[False] = False
    cross_store_transaction_performed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationFiveProviderAuthorityResult:
        if (
            self.tenant_id != self.write_request_set.tenant_id
            or self.run_id != self.write_request_set.run_id
            or self.authority_record_set.write_request_set_sha256
            != self.write_request_set.request_set_sha256
            or tuple(request.position for request in self.write_request_set.requests)
            != tuple(range(5))
        ):
            raise ValueError("five-Provider authority result chain differs")
        recorded = sum(
            record.record_state == "recorded"
            for record in self.authority_record_set.records
        )
        if recorded != self.checkpoint_count_recorded:
            raise ValueError("five-Provider recorded checkpoint count differs")

        incomplete = self.authority_state == (
            "checkpoint_authority_records_incomplete_pending_reconciliation"
        )
        if incomplete:
            if (
                self.authority_record_set.all_checkpoints_recorded
                or self.completion_request is not None
                or self.completion_receipt is not None
                or self.completion_created is not None
                or self.completion_authority_record_invoked
                or self.compensation_completion_recorded
            ):
                raise ValueError("incomplete checkpoint set cannot record completion")
        else:
            if (
                not self.authority_record_set.all_checkpoints_recorded
                or self.checkpoint_count_recorded != 5
                or self.completion_receipt is None
                or self.completion_created is None
                or not self.compensation_completion_recorded
            ):
                raise ValueError("completed five-Provider authority result is incomplete")
            if self.authority_state == "five_provider_compensation_completion_recorded":
                if self.completion_request is None or not self.completion_authority_record_invoked:
                    raise ValueError("recorded completion lacks its authority request")
                if (
                    self.completion_receipt.completion_request_sha256
                    != self.completion_request.request_sha256
                ):
                    raise ValueError("completion receipt differs from its request")
            elif (
                self.completion_request is not None
                or self.completion_authority_record_invoked
                or self.completion_created
            ):
                raise ValueError("reused completion must not invoke the authority writer")
        if self.provider_execution_performed_by_authority or self.cross_store_transaction_performed:
            raise ValueError(
                "authority orchestration cannot invoke Providers or claim a transaction"
            )
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("five-Provider authority result fingerprint is invalid")
        return self


def _validated_inputs(
    execution_result: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
    final_observations: tuple[ProjectionTargetObservation, ...],
) -> tuple[
    ChongqingFederatedCompensationFiveProviderExecutionResult,
    ChongqingFederatedCompensationFiveProviderRequestBundle,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    tuple[ProjectionRepairPlan, ...],
    tuple[ProjectionTargetObservation, ...],
]:
    try:
        return (
            ChongqingFederatedCompensationFiveProviderExecutionResult.model_validate(
                execution_result.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationFiveProviderRequestBundle.model_validate(
                request_bundle.model_dump(mode="python")
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
            tuple(
                ProjectionTargetObservation.model_validate(
                    observation.model_dump(mode="python")
                )
                for observation in final_observations
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationFiveProviderAuthorityValidationError(
            "five-Provider authority input violates a sealed contract"
        ) from exc


def _receipt_set_and_predecessors(
    execution_result: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
):
    registered = (
        execution_result.profiled_execution.source_lineage_execution.deployment_execution
        .registered_execution
    )
    receipt_set = registered.receipt_validation_set
    if (
        registered.state
        is not FederatedCompensationRegisteredReceiptExecutionState
        .COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
        or receipt_set is None
        or receipt_set.receipt_count != 5
        or len(receipt_set.receipt_validations) != 5
        or not receipt_set.provider_receipts_complete
        or execution_result.authority_admission_performed
        or execution_result.checkpoint_authority_write_performed
        or execution_result.compensation_completion_recorded
    ):
        raise ChongqingFederatedCompensationFiveProviderAuthorityValidationError(
            "five-Provider authority requires a complete 5/5 pre-admission receipt set"
        )
    if (
        execution_result.tenant_id != request_bundle.tenant_id
        or execution_result.run_id != request_bundle.run_id
        or execution_result.request_bundle_sha256 != request_bundle.request_bundle_sha256
        or request_bundle.plan_set_sha256 != plan_set.plan_set_sha256
        or request_bundle.materialization_set_sha256
        != materialization.materialization_set_sha256
        or request_bundle.dispatch_intent_sha256 != plan_set.dispatch_intent_sha256
        or receipt_set.plan_set_sha256 != plan_set.plan_set_sha256
        or receipt_set.materialization_set_sha256
        != materialization.materialization_set_sha256
        or receipt_set.dispatch_intent_sha256 != plan_set.dispatch_intent_sha256
        or plan_set.tenant_id != execution_result.tenant_id
        or plan_set.run_id != execution_result.run_id
        or materialization.tenant_id != execution_result.tenant_id
        or materialization.run_id != execution_result.run_id
    ):
        raise ChongqingFederatedCompensationFiveProviderAuthorityValidationError(
            "five-Provider execution, request, receipt, plan, or materialization identity drifted"
        )

    plans_by_hash = {plan.plan_sha256: plan for plan in repair_plans}
    plan_binding_by_position = {
        binding.position: binding for binding in plan_set.plan_bindings
    }
    materialized_by_position = {
        binding.position: binding for binding in materialization.bindings
    }
    bundle_by_position = {item.position: item for item in request_bundle.items}
    if (
        len(repair_plans) != 5
        or len(plans_by_hash) != 5
        or set(plan_binding_by_position) != set(range(5))
        or set(materialized_by_position) != set(range(5))
        or set(bundle_by_position) != set(range(5))
        or {plan.target_engine for plan in repair_plans} != set(ProjectionEngine)
    ):
        raise ChongqingFederatedCompensationFiveProviderAuthorityValidationError(
            "five-Provider authority inputs must cover every engine and position exactly once"
        )

    predecessors: list[FederatedProjectionCompensationCheckpointPredecessor] = []
    for position in range(5):
        binding = plan_binding_by_position[position]
        materialized = materialized_by_position[position]
        bundle_item = bundle_by_position[position]
        plan = plans_by_hash.get(binding.source_plan_sha256)
        if plan is None or (
            bundle_item.source_plan_sha256 != plan.plan_sha256
            or bundle_item.plan_binding_sha256 != binding.plan_binding_sha256
            or bundle_item.materialization_binding_sha256
            != materialized.materialization_binding_sha256
            or bundle_item.target_engine is not plan.target_engine
            or bundle_item.projection_id != plan.projection_id
            or bundle_item.target_ref != plan.target_ref
            or materialized.target_engine is not plan.target_engine
            or materialized.projection_id != plan.projection_id
            or materialized.target_ref != plan.target_ref
        ):
            raise ChongqingFederatedCompensationFiveProviderAuthorityValidationError(
                f"five-Provider authority position {position} differs from its repair plan"
            )
        predecessors.append(
            FederatedProjectionCompensationCheckpointPredecessor(
                position=position,
                tenant_id=plan.tenant_id,
                projection_id=plan.projection_id,
                target_engine=plan.target_engine,
                target_ref=plan.target_ref,
                previous_checkpoint_sha256=plan.previous_checkpoint_sha256,
                next_checkpoint_version=plan.next_checkpoint_version,
            )
        )
    return receipt_set, tuple(predecessors)


def _assert_existing_completion(
    receipt: FederatedProjectionCompensationCompletionReceipt,
    write_request_set: FederatedProjectionCompensationCheckpointWriteRequestSet,
    checkpoint_authority: ProjectionCheckpointAuthorityWriter,
    *,
    completed_by: str,
) -> None:
    request_by_position = {
        request.position: request for request in write_request_set.requests
    }
    target_by_position = {target.position: target for target in receipt.targets}
    if (
        receipt.tenant_id != write_request_set.tenant_id
        or receipt.run_id != write_request_set.run_id
        or receipt.completed_by != completed_by
        or set(target_by_position) != set(request_by_position)
    ):
        raise ChongqingFederatedCompensationFiveProviderAuthorityValidationError(
            "existing compensation completion differs from the sealed five-Provider run"
        )
    for position, request in request_by_position.items():
        target = target_by_position[position]
        checkpoint = request.checkpoint
        if (
            target.projection_id != checkpoint.projection_id
            or target.target_engine is not checkpoint.target_engine
            or target.target_ref != checkpoint.target_ref
            or target.checkpoint_sha256 != checkpoint.checkpoint_sha256
            or target.checkpoint_version != checkpoint.checkpoint_version
            or checkpoint_authority.current(
                tenant_id=request.tenant_id,
                projection_id=checkpoint.projection_id,
                target_engine=checkpoint.target_engine,
                target_ref=checkpoint.target_ref,
            )
            != checkpoint
        ):
            raise ChongqingFederatedCompensationFiveProviderAuthorityValidationError(
                "existing compensation completion checkpoint evidence drifted"
            )


def _result(
    *,
    execution_result: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    receipt_validation_set_sha256: str,
    admission_request: FederatedProjectionCompensationCheckpointAdmissionRequest,
    authority_read_preview: FederatedProjectionCompensationCheckpointAuthorityReadPreview,
    write_intent_set: FederatedProjectionCompensationCheckpointWriteIntentSet,
    write_request_set: FederatedProjectionCompensationCheckpointWriteRequestSet,
    authority_record_set: FederatedProjectionCompensationCheckpointAuthorityRecordSet,
    completion_request: FederatedProjectionCompensationCompletionRequest | None,
    completion_receipt: FederatedProjectionCompensationCompletionReceipt | None,
    completion_created: bool | None,
    authority_state: AuthorityState,
    completion_authority_record_invoked: bool,
) -> ChongqingFederatedCompensationFiveProviderAuthorityResult:
    values = {
        "tenant_id": execution_result.tenant_id,
        "run_id": execution_result.run_id,
        "execution_result_sha256": execution_result.result_sha256,
        "request_bundle_sha256": request_bundle.request_bundle_sha256,
        "receipt_validation_set_sha256": receipt_validation_set_sha256,
        "admission_request": admission_request,
        "authority_read_preview": authority_read_preview,
        "write_intent_set": write_intent_set,
        "write_request_set": write_request_set,
        "authority_record_set": authority_record_set,
        "completion_request": completion_request,
        "completion_receipt": completion_receipt,
        "completion_created": completion_created,
        "authority_state": authority_state,
        "checkpoint_count_recorded": sum(
            record.record_state == "recorded"
            for record in authority_record_set.records
        ),
        "authority_admission_performed": True,
        "checkpoint_authority_write_performed": True,
        "completion_authority_record_invoked": completion_authority_record_invoked,
        "compensation_completion_recorded": completion_receipt is not None,
        "provider_execution_performed_by_authority": False,
        "cross_store_transaction_performed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationFiveProviderAuthorityResult(
        **values,
        result_sha256=_fingerprint(
            ChongqingFederatedCompensationFiveProviderAuthorityResult.schema_id,
            values,
            "result_sha256",
        ),
    )


def record_chongqing_federated_compensation_five_provider_authority(
    execution_result: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
    final_observations: tuple[ProjectionTargetObservation, ...],
    checkpoint_authority: ProjectionCheckpointAuthorityWriter,
    completion_authority: CompensationCompletionAuthority,
    *,
    prepared_by: str,
    writer_subject: str,
    completed_by: str,
    prepared_at: datetime,
    updated_at: datetime,
) -> ChongqingFederatedCompensationFiveProviderAuthorityResult:
    """Record five checkpoints and conditionally record completion."""

    (
        execution_result,
        request_bundle,
        plan_set,
        materialization,
        repair_plans,
        final_observations,
    ) = _validated_inputs(
        execution_result,
        request_bundle,
        plan_set,
        materialization,
        repair_plans,
        final_observations,
    )
    receipt_set, predecessors = _receipt_set_and_predecessors(
        execution_result,
        request_bundle,
        plan_set,
        materialization,
        repair_plans,
    )
    try:
        candidate_set = build_federated_compensation_checkpoint_candidate_set(
            receipt_set,
            plan_set,
            materialization,
            predecessors,
        )
        admission_request = build_federated_compensation_checkpoint_admission_request(
            candidate_set,
            plan_set,
            materialization,
            repair_plans,
        )
        authority_read_preview = (
            build_federated_compensation_checkpoint_authority_read_preview(
                admission_request,
                checkpoint_authority,
            )
        )
        write_intent_set = build_federated_compensation_checkpoint_write_intent_set(
            admission_request,
            authority_read_preview,
            prepared_by=prepared_by,
            prepared_at=prepared_at,
        )
        write_request_set = build_federated_compensation_checkpoint_write_request_set(
            admission_request,
            authority_read_preview,
            write_intent_set,
            final_observations,
            updated_by=writer_subject,
            updated_at=updated_at,
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationFiveProviderAuthorityValidationError(
            "five-Provider authority admission failed before the first checkpoint write"
        ) from exc

    authority_record_set = record_federated_compensation_checkpoint_write_request_set(
        write_request_set,
        checkpoint_authority,
        writer_subject=writer_subject,
    )
    if not authority_record_set.all_checkpoints_recorded:
        return _result(
            execution_result=execution_result,
            request_bundle=request_bundle,
            receipt_validation_set_sha256=receipt_set.validation_set_sha256,
            admission_request=admission_request,
            authority_read_preview=authority_read_preview,
            write_intent_set=write_intent_set,
            write_request_set=write_request_set,
            authority_record_set=authority_record_set,
            completion_request=None,
            completion_receipt=None,
            completion_created=None,
            authority_state=(
                "checkpoint_authority_records_incomplete_pending_reconciliation"
            ),
            completion_authority_record_invoked=False,
        )

    existing_completion = completion_authority.current(execution_result.run_id)
    if existing_completion is not None:
        _assert_existing_completion(
            existing_completion,
            write_request_set,
            checkpoint_authority,
            completed_by=completed_by,
        )
        return _result(
            execution_result=execution_result,
            request_bundle=request_bundle,
            receipt_validation_set_sha256=receipt_set.validation_set_sha256,
            admission_request=admission_request,
            authority_read_preview=authority_read_preview,
            write_intent_set=write_intent_set,
            write_request_set=write_request_set,
            authority_record_set=authority_record_set,
            completion_request=None,
            completion_receipt=existing_completion,
            completion_created=False,
            authority_state="five_provider_compensation_completion_reused",
            completion_authority_record_invoked=False,
        )

    completion_request = build_federated_projection_compensation_completion_request(
        write_request_set,
        authority_record_set,
        checkpoint_authority,
        completed_by=completed_by,
    )
    completion_result = completion_authority.record(completion_request)
    return _result(
        execution_result=execution_result,
        request_bundle=request_bundle,
        receipt_validation_set_sha256=receipt_set.validation_set_sha256,
        admission_request=admission_request,
        authority_read_preview=authority_read_preview,
        write_intent_set=write_intent_set,
        write_request_set=write_request_set,
        authority_record_set=authority_record_set,
        completion_request=completion_request,
        completion_receipt=completion_result.receipt,
        completion_created=completion_result.created,
        authority_state="five_provider_compensation_completion_recorded",
        completion_authority_record_invoked=True,
    )


def record_chongqing_federated_compensation_five_provider_postgres_authority(
    execution_result: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    repair_plans: tuple[ProjectionRepairPlan, ...],
    final_observations: tuple[ProjectionTargetObservation, ...],
    engine: Any,
    *,
    prepared_by: str,
    writer_subject: str,
    completed_by: str,
    prepared_at: datetime,
    updated_at: datetime,
) -> ChongqingFederatedCompensationFiveProviderAuthorityResult:
    """Use the tenant-RLS PostgreSQL checkpoint and completion authorities."""

    checkpoint_authority = PostgresProjectionCheckpointAuthority(engine)
    completion_authority = PostgresFederatedProjectionCompensationCompletionAuthority(
        execution_result.tenant_id,
        engine,
    )
    return record_chongqing_federated_compensation_five_provider_authority(
        execution_result,
        request_bundle,
        plan_set,
        materialization,
        repair_plans,
        final_observations,
        checkpoint_authority,
        completion_authority,
        prepared_by=prepared_by,
        writer_subject=writer_subject,
        completed_by=completed_by,
        prepared_at=prepared_at,
        updated_at=updated_at,
    )


__all__ = [
    "ChongqingFederatedCompensationFiveProviderAuthorityError",
    "ChongqingFederatedCompensationFiveProviderAuthorityResult",
    "ChongqingFederatedCompensationFiveProviderAuthorityValidationError",
    "CompensationCompletionAuthority",
    "record_chongqing_federated_compensation_five_provider_authority",
    "record_chongqing_federated_compensation_five_provider_postgres_authority",
]
