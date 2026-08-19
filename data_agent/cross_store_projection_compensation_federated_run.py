"""Fail-closed execution boundary for one ordered multi-Provider run.

Each concrete Provider adapter owns its native mutation and receipt contract.
This module only binds those outcomes to the already sealed plan/materialization
chain and decides whether the run may continue, must reconcile, or can present a
complete receipt-set candidate.  It never writes checkpoint/completion authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class FederatedCompensationRunError(RuntimeError):
    """The ordered Provider run cannot advance without guessing."""


class FederatedCompensationRunValidationError(FederatedCompensationRunError):
    """The sealed chain or Provider outcome is invalid."""


class FederatedCompensationRunConfigurationError(FederatedCompensationRunError):
    """The native Provider callback registry is incomplete or invalid."""


class FederatedCompensationRunProviderUnknownError(FederatedCompensationRunError):
    """The Provider may have committed, but the caller lacks a trustworthy result."""


class FederatedCompensationRunProviderFailureError(FederatedCompensationRunError):
    """The Provider definitively rejected the mutation before commit."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FederatedCompensationProviderOutcomeStatus(StrEnum):
    COMMITTED = "provider_mutation_committed"
    REPLAYED = "provider_idempotent_replay"
    UNKNOWN = "provider_outcome_unknown"
    FAILED = "provider_mutation_failed"


class FederatedCompensationRunState(StrEnum):
    COMPLETED_PENDING_AUTHORITY = "completed_pending_authority"
    PARTIAL_SUCCESS_PENDING_RECONCILIATION = (
        "partial_success_pending_reconciliation"
    )
    UNKNOWN_PENDING_RECONCILIATION = "unknown_pending_reconciliation"
    FAILED_CLOSED = "failed_closed"


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint(
        {"schema": schema, "data": _json_ready(payload)}
    )


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


class FederatedCompensationRunBinding(_FrozenModel):
    """One ordered Provider position derived from plan and materialization sets."""

    schema_id: ClassVar[str] = "gda.federated-compensation-run-binding.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    source_plan_sha256: Sha256
    plan_binding_sha256: Sha256
    materialization_binding_sha256: Sha256
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    receipt_schema_id: NonEmptyText
    binding_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> FederatedCompensationRunBinding:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"binding_sha256"}),
            "binding_sha256",
        )
        if self.binding_sha256 != expected:
            raise ValueError("federated compensation run binding fingerprint is invalid")
        return self


class FederatedCompensationProviderOutcome(_FrozenModel):
    """Minimal adapter-to-runner result; native receipt payload stays adapter-local."""

    schema_id: ClassVar[str] = "gda.federated-compensation-provider-outcome.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    source_plan_sha256: Sha256
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    status: FederatedCompensationProviderOutcomeStatus
    provider_receipt_sha256: Sha256 | None = None
    error_code: NonEmptyText | None = None
    outcome_sha256: Sha256

    @model_validator(mode="after")
    def _status_contract(self) -> FederatedCompensationProviderOutcome:
        successful = self.status in {
            FederatedCompensationProviderOutcomeStatus.COMMITTED,
            FederatedCompensationProviderOutcomeStatus.REPLAYED,
        }
        if successful and self.provider_receipt_sha256 is None:
            raise ValueError("successful Provider outcome requires a receipt fingerprint")
        if successful and self.error_code is not None:
            raise ValueError("successful Provider outcome cannot contain an error")
        if self.status is FederatedCompensationProviderOutcomeStatus.FAILED:
            if self.error_code is None:
                raise ValueError("failed Provider outcome requires an error code")
            if self.provider_receipt_sha256 is not None:
                raise ValueError("failed Provider outcome cannot carry a receipt")
        if self.status is FederatedCompensationProviderOutcomeStatus.UNKNOWN:
            if self.error_code is None:
                raise ValueError("unknown Provider outcome requires a reconciliation code")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"outcome_sha256"}),
            "outcome_sha256",
        )
        if self.outcome_sha256 != expected:
            raise ValueError("Provider outcome fingerprint is invalid")
        return self


def build_federated_compensation_provider_outcome_from_native_result(
    binding: FederatedCompensationRunBinding,
    native_result: BaseModel,
) -> FederatedCompensationProviderOutcome:
    """Normalize one allowlisted native adapter result without copying its payload."""

    if not isinstance(native_result, BaseModel):
        raise FederatedCompensationRunValidationError(
            "native Provider result must be a validated model"
        )
    try:
        values = native_result.model_dump(mode="python")
    except (TypeError, ValueError) as exc:
        raise FederatedCompensationRunValidationError(
            "native Provider result cannot be serialized"
        ) from exc
    try:
        native_result = type(native_result).model_validate(values)
        values = native_result.model_dump(mode="python")
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedCompensationRunValidationError(
            "native Provider result failed its own sealed contract"
        ) from exc
    if (
        values.get("tenant_id") != binding.tenant_id
        or values.get("run_id") != binding.run_id
        or values.get("position") != binding.position
        or values.get("provider_plan_sha256") != binding.provider_plan_sha256
        or values.get("provider_idempotency_key") != binding.provider_idempotency_key
        or values.get("materialization_binding_sha256")
        != binding.materialization_binding_sha256
    ):
        raise FederatedCompensationRunValidationError(
            "native Provider result differs from its sealed run binding"
        )
    if values.get("provider_execution_performed_by_adapter") is not True:
        raise FederatedCompensationRunValidationError(
            "native Provider result does not prove adapter execution"
        )
    if (
        values.get("checkpoint_authority_write_performed_by_adapter") is not False
        or values.get("compensation_completion_recorded_by_adapter") is not False
    ):
        raise FederatedCompensationRunValidationError(
            "native Provider result claims an authority side effect"
        )
    status_map = {
        "provider_mutation_committed": FederatedCompensationProviderOutcomeStatus.COMMITTED,
        "provider_delete_committed": FederatedCompensationProviderOutcomeStatus.COMMITTED,
        "provider_checkpoint_recorded": FederatedCompensationProviderOutcomeStatus.COMMITTED,
        "provider_idempotent_replay": FederatedCompensationProviderOutcomeStatus.REPLAYED,
    }
    native_status = values.get("provider_execution_status")
    status = status_map.get(native_status)
    if status is None:
        raise FederatedCompensationRunValidationError(
            "native Provider result status is not allowlisted"
        )
    receipt = values.get("receipt")
    if not isinstance(receipt, Mapping):
        raise FederatedCompensationRunValidationError(
            "native Provider result does not contain a structured receipt"
        )
    receipt_commit_ref = receipt.get("provider_commit_ref")
    if not isinstance(receipt_commit_ref, Mapping):
        raise FederatedCompensationRunValidationError(
            "native Provider receipt commit reference is missing"
        )
    receipt_sha256 = receipt_commit_ref.get("receipt_sha256")
    if not isinstance(receipt_sha256, str):
        raise FederatedCompensationRunValidationError(
            "native Provider receipt fingerprint is missing"
        )
    if (
        receipt.get("tenant_id") != binding.tenant_id
        or receipt.get("plan_sha256") != binding.provider_plan_sha256
        or receipt.get("idempotency_key") != binding.provider_idempotency_key
    ):
        raise FederatedCompensationRunValidationError(
            "native Provider receipt differs from its sealed run binding"
        )
    outcome_values = {
        "tenant_id": binding.tenant_id,
        "run_id": binding.run_id,
        "position": binding.position,
        "source_plan_sha256": binding.source_plan_sha256,
        "provider_plan_sha256": binding.provider_plan_sha256,
        "provider_idempotency_key": binding.provider_idempotency_key,
        "status": status,
        "provider_receipt_sha256": receipt_sha256,
        "error_code": None,
    }
    return FederatedCompensationProviderOutcome(
        **outcome_values,
        outcome_sha256=_fingerprint(
            FederatedCompensationProviderOutcome.schema_id,
            outcome_values,
            "outcome_sha256",
        ),
    )


ProviderNativeInvoker = Callable[[FederatedCompensationRunBinding], BaseModel]


class FederatedCompensationProviderInvokerRegistry:
    """Immutable-by-convention allowlist selecting one callback per Provider engine."""

    required_engines = frozenset(ProjectionEngine)

    def __init__(self, invokers: Mapping[ProjectionEngine | str, ProviderNativeInvoker]):
        if not isinstance(invokers, Mapping):
            raise FederatedCompensationRunConfigurationError(
                "Provider invoker registry must be a mapping"
            )
        normalized: dict[ProjectionEngine, ProviderNativeInvoker] = {}
        for raw_engine, invoker in invokers.items():
            try:
                engine = ProjectionEngine(raw_engine)
            except (TypeError, ValueError) as exc:
                raise FederatedCompensationRunConfigurationError(
                    "Provider invoker registry contains an unknown engine"
                ) from exc
            if engine in normalized or not callable(invoker):
                raise FederatedCompensationRunConfigurationError(
                    "Provider invoker registry contains a duplicate or non-callable entry"
                )
            normalized[engine] = invoker
        missing = self.required_engines - normalized.keys()
        if missing:
            missing_names = ",".join(sorted(engine.value for engine in missing))
            raise FederatedCompensationRunConfigurationError(
                f"Provider invoker registry is missing engines: {missing_names}"
            )
        self._invokers = MappingProxyType(normalized)

    @property
    def engines(self) -> tuple[ProjectionEngine, ...]:
        return tuple(sorted(self._invokers, key=lambda engine: engine.value))

    def invoke_native(
        self,
        binding: FederatedCompensationRunBinding,
    ) -> BaseModel:
        """Invoke the sealed engine callback while retaining its native model boundary."""

        try:
            binding = FederatedCompensationRunBinding.model_validate(
                binding.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise FederatedCompensationRunValidationError(
                "Provider invoker received an invalid run binding"
            ) from exc
        invoker = self._invokers.get(binding.target_engine)
        if invoker is None:
            raise FederatedCompensationRunConfigurationError(
                "Provider invoker is not registered for the sealed target engine"
            )
        return invoker(binding)

    def __call__(
        self,
        binding: FederatedCompensationRunBinding,
    ) -> FederatedCompensationProviderOutcome:
        native_result = self.invoke_native(binding)
        return build_federated_compensation_provider_outcome_from_native_result(
            binding,
            native_result,
        )


def execute_federated_compensation_registered_run(
    bindings: tuple[FederatedCompensationRunBinding, ...],
    registry: FederatedCompensationProviderInvokerRegistry,
) -> FederatedCompensationRunResult:
    """Run through the complete engine allowlist and the common outcome boundary."""

    if not isinstance(registry, FederatedCompensationProviderInvokerRegistry):
        raise FederatedCompensationRunConfigurationError(
            "registered federated run requires the governed Provider invoker registry"
        )
    return execute_federated_compensation_run(bindings, registry)


class FederatedCompensationRunStep(_FrozenModel):
    """One attempted position and its sealed, minimal Provider outcome."""

    schema_id: ClassVar[str] = "gda.federated-compensation-run-step.v1"
    binding_sha256: Sha256
    outcome: FederatedCompensationProviderOutcome
    step_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> FederatedCompensationRunStep:
        values = self.model_dump(mode="json", exclude={"step_sha256"})
        expected = _fingerprint(self.schema_id, values, "step_sha256")
        if self.step_sha256 != expected:
            raise ValueError("federated compensation run step fingerprint is invalid")
        return self


class FederatedCompensationRunResult(_FrozenModel):
    """Aggregate result that explicitly separates authority admission from execution."""

    schema_id: ClassVar[str] = "gda.federated-compensation-run-result.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    expected_positions: tuple[int, ...] = Field(min_length=2, max_length=32)
    attempted_positions: tuple[int, ...]
    unattempted_positions: tuple[int, ...]
    steps: tuple[FederatedCompensationRunStep, ...]
    state: FederatedCompensationRunState
    next_action: Literal["admit_receipt_set", "reconcile", "await_operator"]
    provider_receipts_complete: bool
    authority_admission_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _contract(self) -> FederatedCompensationRunResult:
        expected = tuple(range(len(self.expected_positions)))
        if self.expected_positions != expected:
            raise ValueError("federated run positions must be contiguous and ordered")
        if tuple(step.outcome.position for step in self.steps) != self.attempted_positions:
            raise ValueError("federated run attempted positions differ from steps")
        if set(self.attempted_positions) & set(self.unattempted_positions):
            raise ValueError("federated run attempted and unattempted positions overlap")
        if set(self.attempted_positions) | set(self.unattempted_positions) != set(
            self.expected_positions
        ):
            raise ValueError("federated run positions are incomplete")
        if self.provider_receipts_complete != (
            not self.unattempted_positions
            and all(
                step.outcome.status
                in {
                    FederatedCompensationProviderOutcomeStatus.COMMITTED,
                    FederatedCompensationProviderOutcomeStatus.REPLAYED,
                }
                for step in self.steps
            )
        ):
            raise ValueError("federated run receipt completeness is inconsistent")
        if self.state is FederatedCompensationRunState.COMPLETED_PENDING_AUTHORITY:
            if not self.provider_receipts_complete or self.next_action != "admit_receipt_set":
                raise ValueError("completed federated run lacks receipt-set admission")
        elif self.state is FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION:
            if self.next_action != "reconcile" or not any(
                step.outcome.status is FederatedCompensationProviderOutcomeStatus.UNKNOWN
                for step in self.steps
            ):
                raise ValueError("unknown federated run lacks reconciliation evidence")
        elif self.state is FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION:
            if self.next_action != "reconcile" or not any(
                step.outcome.status is FederatedCompensationProviderOutcomeStatus.FAILED
                for step in self.steps
            ):
                raise ValueError("partial federated run lacks failed-provider evidence")
        elif self.state is FederatedCompensationRunState.FAILED_CLOSED:
            if self.next_action != "await_operator" or self.attempted_positions != (0,):
                raise ValueError("failed federated run must stop at its first position")
        expected_sha = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected_sha:
            raise ValueError("federated run result fingerprint is invalid")
        return self


def build_federated_compensation_run_bindings(
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
) -> tuple[FederatedCompensationRunBinding, ...]:
    """Bind every materialized position before any Provider invocation."""

    try:
        plan_set = FederatedProjectionCompensationProviderPlanSet.model_validate(
            plan_set.model_dump(mode="python")
        )
        materialization = (
            FederatedProjectionCompensationProviderMaterializationSet.model_validate(
                materialization.model_dump(mode="python")
            )
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedCompensationRunValidationError(
            "federated run plan/materialization chain is invalid"
        ) from exc
    if (
        materialization.tenant_id != plan_set.tenant_id
        or materialization.run_id != plan_set.run_id
        or materialization.plan_set_sha256 != plan_set.plan_set_sha256
        or len(materialization.bindings) != len(plan_set.plan_bindings)
    ):
        raise FederatedCompensationRunValidationError(
            "federated run materialization differs from Provider plan set"
        )
    bindings: list[FederatedCompensationRunBinding] = []
    for plan, materialized in zip(
        plan_set.plan_bindings,
        materialization.bindings,
        strict=True,
    ):
        if (
            plan.position != materialized.position
            or plan.plan_binding_sha256 != materialized.plan_binding_sha256
            or plan.target_engine is not materialized.target_engine
            or plan.target_ref != materialized.target_ref
            or plan.provider_idempotency_key != materialized.provider_idempotency_key
            or plan.receipt_schema_id != materialized.receipt_schema_id
        ):
            raise FederatedCompensationRunValidationError(
                "federated run plan/materialization position differs"
            )
        values = {
            "tenant_id": plan.tenant_id,
            "run_id": plan.run_id,
            "position": plan.position,
            "projection_id": materialized.projection_id,
            "target_engine": plan.target_engine,
            "target_ref": plan.target_ref,
            "source_plan_sha256": plan.source_plan_sha256,
            "plan_binding_sha256": plan.plan_binding_sha256,
            "materialization_binding_sha256": materialized.materialization_binding_sha256,
            "provider_plan_sha256": materialized.provider_plan_sha256,
            "provider_idempotency_key": materialized.provider_idempotency_key,
            "receipt_schema_id": materialized.receipt_schema_id,
        }
        bindings.append(
            FederatedCompensationRunBinding(
                **values,
                binding_sha256=_fingerprint(
                    FederatedCompensationRunBinding.schema_id,
                    values,
                    "binding_sha256",
                ),
            )
        )
    return tuple(bindings)


ProviderInvoker = Callable[
    [FederatedCompensationRunBinding], FederatedCompensationProviderOutcome
]


def _result(
    *,
    bindings: tuple[FederatedCompensationRunBinding, ...],
    steps: tuple[FederatedCompensationRunStep, ...],
) -> FederatedCompensationRunResult:
    expected_positions = tuple(binding.position for binding in bindings)
    attempted_positions = tuple(step.outcome.position for step in steps)
    unattempted_positions = tuple(
        position for position in expected_positions if position not in attempted_positions
    )
    statuses = tuple(step.outcome.status for step in steps)
    receipts_complete = not unattempted_positions and all(
        status
        in {
            FederatedCompensationProviderOutcomeStatus.COMMITTED,
            FederatedCompensationProviderOutcomeStatus.REPLAYED,
        }
        for status in statuses
    )
    if receipts_complete:
        state = FederatedCompensationRunState.COMPLETED_PENDING_AUTHORITY
        next_action = "admit_receipt_set"
    elif any(status is FederatedCompensationProviderOutcomeStatus.UNKNOWN for status in statuses):
        state = FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION
        next_action = "reconcile"
    elif any(status is FederatedCompensationProviderOutcomeStatus.FAILED for status in statuses):
        state = (
            FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION
            if any(
                status
                in {
                    FederatedCompensationProviderOutcomeStatus.COMMITTED,
                    FederatedCompensationProviderOutcomeStatus.REPLAYED,
                }
                for status in statuses
            )
            else FederatedCompensationRunState.FAILED_CLOSED
        )
        next_action = (
            "reconcile"
            if state is not FederatedCompensationRunState.FAILED_CLOSED
            else "await_operator"
        )
    else:
        raise FederatedCompensationRunValidationError(
            "federated run ended without a Provider outcome"
        )
    values = {
        "tenant_id": bindings[0].tenant_id,
        "run_id": bindings[0].run_id,
        "expected_positions": expected_positions,
        "attempted_positions": attempted_positions,
        "unattempted_positions": unattempted_positions,
        "steps": steps,
        "state": state,
        "next_action": next_action,
        "provider_receipts_complete": receipts_complete,
        "authority_admission_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return FederatedCompensationRunResult(
        **values,
        result_sha256=_fingerprint(
            FederatedCompensationRunResult.schema_id,
            values,
            "result_sha256",
        ),
    )


def execute_federated_compensation_run(
    bindings: tuple[FederatedCompensationRunBinding, ...],
    invoke: ProviderInvoker,
) -> FederatedCompensationRunResult:
    """Invoke ordered Providers and stop at the first non-success outcome."""

    if len(bindings) < 2 or len(bindings) > 32:
        raise FederatedCompensationRunValidationError(
            "federated compensation run requires between 2 and 32 bindings"
        )
    if tuple(binding.position for binding in bindings) != tuple(range(len(bindings))):
        raise FederatedCompensationRunValidationError(
            "federated compensation run bindings must be contiguous and ordered"
        )
    tenant_ids = {binding.tenant_id for binding in bindings}
    run_ids = {binding.run_id for binding in bindings}
    if len(tenant_ids) != 1 or len(run_ids) != 1:
        raise FederatedCompensationRunValidationError(
            "federated compensation run cannot cross tenant or run boundaries"
        )
    steps: list[FederatedCompensationRunStep] = []
    for binding in bindings:
        try:
            outcome = invoke(binding)
            outcome = FederatedCompensationProviderOutcome.model_validate(
                outcome.model_dump(mode="python")
            )
        except FederatedCompensationRunProviderUnknownError as exc:
            values = {
                "tenant_id": binding.tenant_id,
                "run_id": binding.run_id,
                "position": binding.position,
                "source_plan_sha256": binding.source_plan_sha256,
                "provider_plan_sha256": binding.provider_plan_sha256,
                "provider_idempotency_key": binding.provider_idempotency_key,
                "status": FederatedCompensationProviderOutcomeStatus.UNKNOWN,
                "provider_receipt_sha256": None,
                "error_code": str(exc)[:128] or "provider_outcome_unknown",
            }
            outcome = FederatedCompensationProviderOutcome(
                **values,
                outcome_sha256=_fingerprint(
                    FederatedCompensationProviderOutcome.schema_id,
                    values,
                    "outcome_sha256",
                ),
            )
        except FederatedCompensationRunProviderFailureError as exc:
            values = {
                "tenant_id": binding.tenant_id,
                "run_id": binding.run_id,
                "position": binding.position,
                "source_plan_sha256": binding.source_plan_sha256,
                "provider_plan_sha256": binding.provider_plan_sha256,
                "provider_idempotency_key": binding.provider_idempotency_key,
                "status": FederatedCompensationProviderOutcomeStatus.FAILED,
                "provider_receipt_sha256": None,
                "error_code": str(exc)[:128] or "provider_mutation_failed",
            }
            outcome = FederatedCompensationProviderOutcome(
                **values,
                outcome_sha256=_fingerprint(
                    FederatedCompensationProviderOutcome.schema_id,
                    values,
                    "outcome_sha256",
                ),
            )
        except (
            FederatedCompensationRunConfigurationError,
            FederatedCompensationRunValidationError,
        ):
            raise
        except Exception:  # Provider side effects may be unknown to the caller.
            values = {
                "tenant_id": binding.tenant_id,
                "run_id": binding.run_id,
                "position": binding.position,
                "source_plan_sha256": binding.source_plan_sha256,
                "provider_plan_sha256": binding.provider_plan_sha256,
                "provider_idempotency_key": binding.provider_idempotency_key,
                "status": FederatedCompensationProviderOutcomeStatus.UNKNOWN,
                "provider_receipt_sha256": None,
                "error_code": "unclassified_provider_exception",
            }
            outcome = FederatedCompensationProviderOutcome(
                **values,
                outcome_sha256=_fingerprint(
                    FederatedCompensationProviderOutcome.schema_id,
                    values,
                    "outcome_sha256",
                ),
            )
        if (
            outcome.tenant_id != binding.tenant_id
            or outcome.run_id != binding.run_id
            or outcome.position != binding.position
            or outcome.source_plan_sha256 != binding.source_plan_sha256
            or outcome.provider_plan_sha256 != binding.provider_plan_sha256
            or outcome.provider_idempotency_key != binding.provider_idempotency_key
        ):
            raise FederatedCompensationRunValidationError(
                "Provider outcome differs from its sealed run binding"
            )
        values = {"binding_sha256": binding.binding_sha256, "outcome": outcome}
        steps.append(
            FederatedCompensationRunStep(
                **values,
                step_sha256=_fingerprint(
                    FederatedCompensationRunStep.schema_id,
                    values,
                    "step_sha256",
                ),
            )
        )
        if outcome.status not in {
            FederatedCompensationProviderOutcomeStatus.COMMITTED,
            FederatedCompensationProviderOutcomeStatus.REPLAYED,
        }:
            break
    return _result(bindings=bindings, steps=tuple(steps))


def seal_federated_compensation_run_result(
    bindings: tuple[FederatedCompensationRunBinding, ...],
    steps: tuple[FederatedCompensationRunStep, ...],
) -> FederatedCompensationRunResult:
    """Seal an already-observed ordered run without invoking a Provider.

    Recovery orchestration uses this boundary after rebuilding prior receipts,
    resolving one unknown position, and invoking only the still-unattempted
    suffix.  It intentionally performs no callback or authority write.
    """

    return _result(bindings=bindings, steps=steps)


__all__ = [
    "FederatedCompensationProviderOutcome",
    "FederatedCompensationProviderOutcomeStatus",
    "FederatedCompensationProviderInvokerRegistry",
    "FederatedCompensationRunBinding",
    "FederatedCompensationRunConfigurationError",
    "FederatedCompensationRunError",
    "FederatedCompensationRunProviderFailureError",
    "FederatedCompensationRunProviderUnknownError",
    "FederatedCompensationRunResult",
    "FederatedCompensationRunState",
    "FederatedCompensationRunStep",
    "FederatedCompensationRunValidationError",
    "build_federated_compensation_provider_outcome_from_native_result",
    "build_federated_compensation_run_bindings",
    "execute_federated_compensation_registered_run",
    "execute_federated_compensation_run",
    "seal_federated_compensation_run_result",
]
