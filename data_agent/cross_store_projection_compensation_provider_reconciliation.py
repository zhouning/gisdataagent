"""Provider-neutral unknown-outcome evidence contract.

Concrete Provider wrappers supply their sealed request, target registry,
receipt recovery, observation, and native adapter callback. This module owns
only the cross-Provider decision contract; it never opens a connection or
constructs a Provider payload.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    ValidationError,
    model_validator,
)

from .cross_store_projection_compensation_chongqing_source_lineage_reconciliation import (
    ChongqingFederatedCompensationSourceLineageReconciliationCase,
    ChongqingFederatedCompensationSourceLineageReconciliationItem,
)
from .cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderOutcome,
    FederatedCompensationProviderOutcomeStatus,
)
from .cross_store_projection_consistency import ProjectionEngine, ProjectionTargetObservation
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class ProviderReconciliationError(RuntimeError):
    """A Provider unknown outcome cannot be reconciled without guessing."""


class ProviderReconciliationValidationError(ProviderReconciliationError):
    """The sealed request, stopped case, or evidence is invalid."""


class ProviderReconciliationConfigurationError(ProviderReconciliationError):
    """The governed Provider observation channel is unavailable."""


class ProviderReconciliationExecutionError(ProviderReconciliationError):
    """Observation or conditional resume failed."""


class ProviderReconciliationConflictError(ProviderReconciliationError):
    """Provider state changed after a safe-to-resume observation."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


def _target_state_fingerprint(observation: ProjectionTargetObservation) -> str:
    return canonical_json_fingerprint(
        {
            "schema": "gda.provider-target-state.v1",
            "tenant_id": observation.tenant_id,
            "projection_id": observation.projection_id,
            "target_engine": observation.target_engine.value,
            "target_ref": observation.target_ref,
            "target_exists": observation.target_exists,
            "target_content_sha256": observation.observed_content_sha256,
            "target_row_count": observation.observed_row_count,
        }
    )


ObservationDecision = Literal[
    "provider_commit_confirmed_from_persisted_receipt",
    "provider_not_committed_safe_to_resume",
    "indeterminate_operator_required",
]
ObservationReason = Literal[
    "persisted_receipt_and_current_target_confirm_commit",
    "receipt_absent_target_matches_sealed_observation",
    "receipt_absent_target_differs_from_sealed_observation",
    "persisted_receipt_or_current_target_validation_failed",
    "target_changed_after_persisted_receipt_verification",
]


class ProviderReconciliationObservation(_FrozenModel):
    """Sealed, non-mutating evidence for one unknown Provider position."""

    schema_id: ClassVar[str] = "gda.provider-reconciliation-observation.v1"
    provider: NonEmptyText
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    target_engine: ProjectionEngine
    reconciliation_case_sha256: Sha256
    reconciliation_item_sha256: Sha256
    unknown_outcome_sha256: Sha256
    request_sha256: Sha256
    execution_plan_sha256: Sha256
    source_plan_sha256: Sha256
    materialization_binding_sha256: Sha256
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    sealed_pre_mutation_state_sha256: Sha256
    current_target_state_sha256: Sha256
    current_observation: ProjectionTargetObservation
    recovered_receipt: SerializeAsAny[BaseModel] | None = None
    reconciled_provider_outcome: FederatedCompensationProviderOutcome | None = None
    decision: ObservationDecision
    reason_code: ObservationReason
    reconciled_by: NonEmptyText = Field(
        pattern=r"^(human|workload|agent):[^\s]{1,128}$"
    )
    reconciled_at: datetime
    provider_observation_performed: Literal[True] = True
    provider_retry_performed: Literal[False] = False
    provider_mutation_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    cross_store_transaction_performed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    observation_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ProviderReconciliationObservation:
        if self.reconciled_at.tzinfo is None or self.reconciled_at.utcoffset() is None:
            raise ValueError("Provider reconciliation timestamp must be timezone-aware")
        if self.current_observation.target_engine is not self.target_engine:
            raise ValueError("Provider reconciliation target engine differs")
        if (
            self.current_observation.tenant_id != self.tenant_id
            or _target_state_fingerprint(self.current_observation)
            != self.current_target_state_sha256
        ):
            raise ValueError("Provider reconciliation current target evidence differs")
        receipt_present = self.recovered_receipt is not None
        outcome_present = self.reconciled_provider_outcome is not None
        if receipt_present != outcome_present:
            raise ValueError("Provider receipt and reconciled outcome presence differs")
        if self.decision == "provider_commit_confirmed_from_persisted_receipt":
            if (
                not receipt_present
                or self.reason_code
                != "persisted_receipt_and_current_target_confirm_commit"
            ):
                raise ValueError("confirmed Provider commit lacks verified receipt evidence")
        elif self.decision == "provider_not_committed_safe_to_resume":
            if (
                receipt_present
                or self.reason_code
                != "receipt_absent_target_matches_sealed_observation"
                or self.current_target_state_sha256
                != self.sealed_pre_mutation_state_sha256
            ):
                raise ValueError("safe Provider resume evidence is inconsistent")
        elif self.reason_code not in {
            "receipt_absent_target_differs_from_sealed_observation",
            "persisted_receipt_or_current_target_validation_failed",
            "target_changed_after_persisted_receipt_verification",
        }:
            raise ValueError("operator-required Provider evidence has an invalid reason")
        if receipt_present:
            receipt = self.recovered_receipt
            outcome = self.reconciled_provider_outcome
            assert receipt is not None and outcome is not None
            provider_commit_ref = receipt.model_dump(mode="python").get(
                "provider_commit_ref", {}
            )
            if (
                not isinstance(provider_commit_ref, dict)
                or provider_commit_ref.get("provider") != self.provider
                or receipt.model_dump(mode="python").get("tenant_id") != self.tenant_id
                or receipt.model_dump(mode="python").get("plan_sha256")
                != self.provider_plan_sha256
                or receipt.model_dump(mode="python").get("idempotency_key")
                != self.provider_idempotency_key
                or outcome.tenant_id != self.tenant_id
                or outcome.run_id != self.run_id
                or outcome.position != self.position
                or outcome.source_plan_sha256 != self.source_plan_sha256
                or outcome.provider_plan_sha256 != self.provider_plan_sha256
                or outcome.provider_idempotency_key != self.provider_idempotency_key
                or outcome.status
                is not FederatedCompensationProviderOutcomeStatus.COMMITTED
                or outcome.provider_receipt_sha256
                != provider_commit_ref.get("receipt_sha256")
            ):
                raise ValueError("recovered Provider receipt differs from outcome")
        if (
            not self.provider_observation_performed
            or self.provider_retry_performed
            or self.provider_mutation_performed
            or self.checkpoint_authority_write_performed
            or self.compensation_completion_recorded
            or self.cross_store_transaction_performed
        ):
            raise ValueError("Provider observation claims a side effect")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"observation_sha256"}),
            "observation_sha256",
        )
        if self.observation_sha256 != expected:
            raise ValueError("Provider reconciliation observation fingerprint is invalid")
        return self


class ProviderReconciliationResumeResult(_FrozenModel):
    """Result of a resume admitted by a fresh safe-to-resume observation."""

    schema_id: ClassVar[str] = "gda.provider-reconciliation-resume-result.v1"
    provider: NonEmptyText
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    reconciliation_case_sha256: Sha256
    safe_observation_sha256: Sha256
    live_observation_sha256: Sha256
    request_sha256: Sha256
    mutation_result: SerializeAsAny[BaseModel]
    reconciled_provider_outcome: FederatedCompensationProviderOutcome
    provider_execution_status: NonEmptyText
    resume_state: Literal[
        "provider_resumed_with_new_commit",
        "provider_resume_converged_by_idempotent_replay",
    ]
    resumed_by: NonEmptyText = Field(pattern=r"^(human|workload|agent):[^\s]{1,128}$")
    resumed_at: datetime
    provider_resume_invocation_performed: Literal[True] = True
    provider_mutation_performed: bool
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    cross_store_transaction_performed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ProviderReconciliationResumeResult:
        result = self.mutation_result.model_dump(mode="python")
        outcome = self.reconciled_provider_outcome
        if self.resumed_at.tzinfo is None or self.resumed_at.utcoffset() is None:
            raise ValueError("Provider resume timestamp must be timezone-aware")
        receipt = result.get("receipt")
        receipt_values = receipt if isinstance(receipt, dict) else {}
        commit_ref = receipt_values.get("provider_commit_ref", {})
        if (
            result.get("tenant_id") != self.tenant_id
            or result.get("run_id") != self.run_id
            or result.get("position") != self.position
            or result.get("request_sha256") != self.request_sha256
            or result.get("provider_execution_status") != self.provider_execution_status
            or outcome.tenant_id != self.tenant_id
            or outcome.run_id != self.run_id
            or outcome.position != self.position
            or outcome.provider_receipt_sha256 != commit_ref.get("receipt_sha256")
        ):
            raise ValueError("Provider resume result chain differs")
        replayed = self.provider_execution_status == "provider_idempotent_replay"
        expected_state = (
            "provider_resume_converged_by_idempotent_replay"
            if replayed
            else "provider_resumed_with_new_commit"
        )
        expected_status = (
            FederatedCompensationProviderOutcomeStatus.REPLAYED
            if replayed
            else FederatedCompensationProviderOutcomeStatus.COMMITTED
        )
        if (
            self.resume_state != expected_state
            or outcome.status is not expected_status
            or self.provider_mutation_performed
            != bool(result.get("provider_mutation_performed"))
            or not self.provider_resume_invocation_performed
            or self.checkpoint_authority_write_performed
            or self.compensation_completion_recorded
            or self.cross_store_transaction_performed
        ):
            raise ValueError("Provider resume state is inconsistent")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("Provider resume result fingerprint is invalid")
        return self


RequestT = TypeVar("RequestT", bound=BaseModel)
ReceiptT = TypeVar("ReceiptT", bound=BaseModel)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderReconciliationValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _validated_chain(
    request: RequestT,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    *,
    executor: Any,
    engine: ProjectionEngine,
) -> tuple[
    RequestT,
    ChongqingFederatedCompensationSourceLineageReconciliationCase,
    ChongqingFederatedCompensationSourceLineageReconciliationItem,
    Any,
]:
    if not isinstance(request, BaseModel):
        raise ProviderReconciliationValidationError("Provider request must be a sealed model")
    try:
        request = type(request).model_validate(request.model_dump(mode="python"))
        reconciliation_case = (
            ChongqingFederatedCompensationSourceLineageReconciliationCase.model_validate(
                reconciliation_case.model_dump(mode="python")
            )
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ProviderReconciliationValidationError(
            "Provider reconciliation input violates a sealed contract"
        ) from exc
    plan = request.execution_plan
    item = next(
        (
            candidate
            for candidate in reconciliation_case.items
            if candidate.position == plan.position
        ),
        None,
    )
    if (
        item is None
        or request.tenant_id != reconciliation_case.tenant_id
        or request.run_id != reconciliation_case.run_id
        or item.target_engine is not engine
        or item.outcome_class != "provider_outcome_unknown"
        or item.outcome_sha256 is None
        or item.reconciliation_action != "observe_provider_outcome_before_any_retry"
        or item.source_plan_sha256 != plan.source_plan.plan_sha256
        or item.provider_plan_sha256 != plan.provider_plan_sha256
        or item.target_ref != plan.target_ref
    ):
        raise ProviderReconciliationValidationError(
            "Provider request does not match the unknown stopped case position"
        )
    try:
        registered = executor.registry.resolve(
            tenant_id=request.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
    except Exception as exc:
        raise ProviderReconciliationValidationError(
            "Provider reconciliation target is not registered"
        ) from exc
    request_target = getattr(request, "target", None)
    if request_target is not None and registered != request_target:
        raise ProviderReconciliationValidationError(
            "Provider reconciliation target differs from the sealed request"
        )
    return request, reconciliation_case, item, registered


def _outcome(
    request: BaseModel,
    receipt: BaseModel,
    *,
    status: FederatedCompensationProviderOutcomeStatus,
) -> FederatedCompensationProviderOutcome:
    plan = request.execution_plan
    receipt_values = receipt.model_dump(mode="python")
    commit_ref = receipt_values.get("provider_commit_ref", {})
    values = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "position": plan.position,
        "source_plan_sha256": plan.source_plan.plan_sha256,
        "provider_plan_sha256": plan.provider_plan_sha256,
        "provider_idempotency_key": plan.provider_idempotency_key,
        "status": status,
        "provider_receipt_sha256": commit_ref.get("receipt_sha256"),
        "error_code": None,
    }
    return FederatedCompensationProviderOutcome(
        **values,
        outcome_sha256=_fingerprint(
            FederatedCompensationProviderOutcome.schema_id,
            values,
            "outcome_sha256",
        ),
    )


def observe_provider_unknown_outcome(
    request: RequestT,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    *,
    executor: Any,
    engine: ProjectionEngine,
    provider: str,
    recover_receipt: Callable[[Any, Any], ReceiptT | None],
    observe_target: Callable[[Any, Any], ProjectionTargetObservation],
    validation_errors: tuple[type[Exception], ...] = (),
    configuration_errors: tuple[type[Exception], ...] = (),
    execution_errors: tuple[type[Exception], ...] = (),
    reconciled_by: str,
    reconciled_at: datetime,
) -> ProviderReconciliationObservation:
    request, reconciliation_case, item, registered = _validated_chain(
        request, reconciliation_case, executor=executor, engine=engine
    )
    reconciled_at = _aware_utc(reconciled_at, "reconciled_at")
    receipt_validation_failed = False
    try:
        receipt = recover_receipt(executor, request.execution_plan)
    except validation_errors:
        receipt = None
        receipt_validation_failed = True
    except configuration_errors as exc:
        raise ProviderReconciliationConfigurationError(str(exc)) from exc
    except execution_errors as exc:
        raise ProviderReconciliationExecutionError(str(exc)) from exc
    try:
        current = observe_target(executor, registered)
    except validation_errors as exc:
        raise ProviderReconciliationValidationError(str(exc)) from exc
    except configuration_errors as exc:
        raise ProviderReconciliationConfigurationError(str(exc)) from exc
    except execution_errors as exc:
        raise ProviderReconciliationExecutionError(str(exc)) from exc
    sealed_state_sha256 = _target_state_fingerprint(request.execution_plan.observation)
    current_state_sha256 = _target_state_fingerprint(current)
    outcome: FederatedCompensationProviderOutcome | None = None
    if receipt_validation_failed:
        decision: ObservationDecision = "indeterminate_operator_required"
        reason: ObservationReason = "persisted_receipt_or_current_target_validation_failed"
    elif receipt is not None:
        outcome = _outcome(
            request,
            receipt,
            status=FederatedCompensationProviderOutcomeStatus.COMMITTED,
        )
        values = receipt.model_dump(mode="python")
        receipt_state_matches = (
            current.target_exists == values.get("target_exists")
            and current.observed_content_sha256 == values.get("target_content_sha256")
            and current.observed_row_count == values.get("target_row_count")
        )
        if receipt_state_matches:
            decision = "provider_commit_confirmed_from_persisted_receipt"
            reason = "persisted_receipt_and_current_target_confirm_commit"
        else:
            decision = "indeterminate_operator_required"
            reason = "target_changed_after_persisted_receipt_verification"
    elif current_state_sha256 == sealed_state_sha256:
        decision = "provider_not_committed_safe_to_resume"
        reason = "receipt_absent_target_matches_sealed_observation"
    else:
        decision = "indeterminate_operator_required"
        reason = "receipt_absent_target_differs_from_sealed_observation"
    plan = request.execution_plan
    values = {
        "provider": provider,
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "position": plan.position,
        "target_engine": engine,
        "reconciliation_case_sha256": reconciliation_case.case_sha256,
        "reconciliation_item_sha256": item.item_sha256,
        "unknown_outcome_sha256": item.outcome_sha256,
        "request_sha256": request.request_sha256,
        "execution_plan_sha256": plan.execution_plan_sha256,
        "source_plan_sha256": plan.source_plan.plan_sha256,
        "materialization_binding_sha256": plan.materialization_binding_sha256,
        "provider_plan_sha256": plan.provider_plan_sha256,
        "provider_idempotency_key": plan.provider_idempotency_key,
        "sealed_pre_mutation_state_sha256": sealed_state_sha256,
        "current_target_state_sha256": current_state_sha256,
        "current_observation": current,
        "recovered_receipt": receipt,
        "reconciled_provider_outcome": outcome,
        "decision": decision,
        "reason_code": reason,
        "reconciled_by": reconciled_by,
        "reconciled_at": reconciled_at,
        "provider_observation_performed": True,
        "provider_retry_performed": False,
        "provider_mutation_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "cross_store_transaction_performed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    try:
        return ProviderReconciliationObservation(
            **values,
            observation_sha256=_fingerprint(
                ProviderReconciliationObservation.schema_id,
                values,
                "observation_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ProviderReconciliationValidationError(
            "Provider reconciliation observation is invalid"
        ) from exc


def resume_provider_unknown_outcome(
    request: RequestT,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    safe_observation: ProviderReconciliationObservation,
    *,
    executor: Any,
    engine: ProjectionEngine,
    provider: str,
    recover_receipt: Callable[[Any, Any], ReceiptT | None],
    observe_target: Callable[[Any, Any], ProjectionTargetObservation],
    execute_mutation: Callable[[RequestT, Any], BaseModel],
    validation_errors: tuple[type[Exception], ...] = (),
    configuration_errors: tuple[type[Exception], ...] = (),
    execution_errors: tuple[type[Exception], ...] = (),
    resumed_by: str,
    resumed_at: datetime,
) -> ProviderReconciliationResumeResult:
    request, reconciliation_case, _, _ = _validated_chain(
        request, reconciliation_case, executor=executor, engine=engine
    )
    try:
        safe_observation = ProviderReconciliationObservation.model_validate(
            safe_observation.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ProviderReconciliationValidationError(
            "Provider safe-to-resume evidence violates its sealed contract"
        ) from exc
    plan = request.execution_plan
    if (
        safe_observation.provider != provider
        or safe_observation.target_engine is not engine
        or safe_observation.decision != "provider_not_committed_safe_to_resume"
        or safe_observation.request_sha256 != request.request_sha256
        or safe_observation.reconciliation_case_sha256 != reconciliation_case.case_sha256
        or safe_observation.position != plan.position
        or safe_observation.execution_plan_sha256 != plan.execution_plan_sha256
        or safe_observation.source_plan_sha256 != plan.source_plan.plan_sha256
        or safe_observation.provider_plan_sha256 != plan.provider_plan_sha256
        or safe_observation.provider_idempotency_key != plan.provider_idempotency_key
        or safe_observation.current_observation.tenant_id != request.tenant_id
        or safe_observation.current_observation.projection_id != plan.projection_id
        or safe_observation.current_observation.target_ref != plan.target_ref
    ):
        raise ProviderReconciliationValidationError(
            "Provider resume requires matching safe-to-resume evidence"
        )
    resumed_at = _aware_utc(resumed_at, "resumed_at")
    live_observation = observe_provider_unknown_outcome(
        request,
        reconciliation_case,
        executor=executor,
        engine=engine,
        provider=provider,
        recover_receipt=recover_receipt,
        observe_target=observe_target,
        validation_errors=validation_errors,
        configuration_errors=configuration_errors,
        execution_errors=execution_errors,
        reconciled_by=resumed_by,
        reconciled_at=resumed_at,
    )
    if live_observation.decision != "provider_not_committed_safe_to_resume":
        raise ProviderReconciliationConflictError(
            f"{provider} state changed after observation; reconcile again before resume"
        )
    try:
        mutation_result = execute_mutation(request, executor)
    except validation_errors as exc:
        raise ProviderReconciliationValidationError(str(exc)) from exc
    except configuration_errors as exc:
        raise ProviderReconciliationConfigurationError(str(exc)) from exc
    except execution_errors as exc:
        raise ProviderReconciliationExecutionError(str(exc)) from exc
    result_values = mutation_result.model_dump(mode="python")
    native_status = result_values.get("provider_execution_status")
    if native_status not in {
        "provider_mutation_committed",
        "provider_delete_committed",
        "provider_checkpoint_recorded",
        "provider_idempotent_replay",
    }:
        raise ProviderReconciliationExecutionError(
            "Provider resume returned an unallowlisted execution status"
        )
    receipt = getattr(mutation_result, "receipt", None)
    if not isinstance(receipt, BaseModel):
        raise ProviderReconciliationExecutionError(
            "Provider resume returned no structured receipt"
        )
    replayed = native_status == "provider_idempotent_replay"
    outcome = _outcome(
        request,
        receipt,
        status=(
            FederatedCompensationProviderOutcomeStatus.REPLAYED
            if replayed
            else FederatedCompensationProviderOutcomeStatus.COMMITTED
        ),
    )
    values = {
        "provider": provider,
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "position": plan.position,
        "reconciliation_case_sha256": reconciliation_case.case_sha256,
        "safe_observation_sha256": safe_observation.observation_sha256,
        "live_observation_sha256": live_observation.observation_sha256,
        "request_sha256": request.request_sha256,
        "mutation_result": mutation_result,
        "reconciled_provider_outcome": outcome,
        "provider_execution_status": native_status,
        "resume_state": (
            "provider_resume_converged_by_idempotent_replay"
            if replayed
            else "provider_resumed_with_new_commit"
        ),
        "resumed_by": resumed_by,
        "resumed_at": resumed_at,
        "provider_resume_invocation_performed": True,
        "provider_mutation_performed": bool(result_values.get("provider_mutation_performed")),
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "cross_store_transaction_performed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    try:
        return ProviderReconciliationResumeResult(
            **values,
            result_sha256=_fingerprint(
                ProviderReconciliationResumeResult.schema_id,
                values,
                "result_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ProviderReconciliationExecutionError(
            "Provider resume result is invalid"
        ) from exc


__all__ = [
    "ProviderReconciliationConfigurationError",
    "ProviderReconciliationConflictError",
    "ProviderReconciliationError",
    "ProviderReconciliationExecutionError",
    "ProviderReconciliationObservation",
    "ProviderReconciliationResumeResult",
    "ProviderReconciliationValidationError",
    "observe_provider_unknown_outcome",
    "resume_provider_unknown_outcome",
]
